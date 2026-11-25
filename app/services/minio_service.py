import io
import json
import os
import uuid
from urllib.parse import urlparse

import certifi
from flask import Response, abort, current_app
from minio import Minio
from minio.error import MinioException, S3Error
from urllib3 import PoolManager, Retry, Timeout
from urllib3.exceptions import HTTPError


class MinioService:
    def __init__(self, app=None):
        self.client = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.client = None
        minio_endpoint = app.config.get('MINIO_ENDPOINT')
        access_key = app.config.get('MINIO_ACCESS_KEY')
        secret_key = app.config.get('MINIO_SECRET_KEY')
        secure = app.config.get('MINIO_SECURE', False)

        if minio_endpoint and access_key and secret_key:
            client = Minio(
                minio_endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                http_client=PoolManager(
                    timeout=Timeout(connect=5.0, read=30.0),
                    cert_reqs='CERT_REQUIRED',
                    ca_certs=os.environ.get('SSL_CERT_FILE') or certifi.where(),
                    retries=Retry(total=1, backoff_factor=0.2),
                ),
            )
            self._configure_bucket(client, app.config['MINIO_BUCKET_NAME'])
            self.client = client

    def _configure_bucket(self, client, bucket_name):
        if not client.bucket_exists(bucket_name):
            try:
                client.make_bucket(bucket_name)
            except S3Error as error:
                if error.code != 'BucketAlreadyOwnedByYou':
                    raise

        # Publicar solo los documentos de concursos y las imágenes WebP históricas.
        # Los adjuntos de postulaciones existentes y nuevos se descargan desde el panel.
        bucket_arn = f'arn:aws:s3:::{bucket_name}'
        policy = {
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Principal': {'AWS': ['*']},
                'Action': ['s3:GetObject'],
                'Resource': [
                    f'{bucket_arn}/concursos/docs/*',
                    f'{bucket_arn}/????????-????-????-????-????????????.webp',
                ],
            }],
        }
        client.set_bucket_policy(bucket_name, json.dumps(policy))

    def upload_document(self, file_storage, prefix='concursos/docs/'):
        """
        Sube un archivo PDF a MinIO. Retorna la clave (key) del objeto.
        El archivo debe ser un FileStorage de Flask con content_type application/pdf
        y contenido PDF.
        """
        if not self.client:
            raise Exception("MinIO client not initialized")

        filename_lower = (getattr(file_storage, 'filename', '') or '').lower()
        if not filename_lower.endswith('.pdf'):
            raise ValueError('Solo se permiten archivos en formato PDF')

        file_storage.seek(0, 2)
        length = file_storage.tell()
        file_storage.seek(0)

        if length == 0:
            raise ValueError('El archivo PDF está vacío')
        if b'%PDF-' not in file_storage.read(1024):
            raise ValueError('El archivo seleccionado no es un PDF válido')
        file_storage.seek(0)

        bucket = current_app.config['MINIO_BUCKET_NAME']
        key = f"{prefix}{uuid.uuid4()}.pdf"

        self.client.put_object(
            bucket,
            key,
            file_storage.stream,
            length,
            content_type='application/pdf',
        )

        return key

    def upload_application_file(self, file_storage, prefix='postulaciones/', allowed_extensions=None, max_size=None):
        """Sube archivos administrativos permitidos a MinIO y retorna la clave del objeto."""
        if not self.client:
            raise Exception("MinIO client not initialized")

        original_name = getattr(file_storage, 'filename', '') or ''
        if '.' not in original_name:
            raise ValueError('El archivo no tiene extensión válida')

        extension = original_name.rsplit('.', 1)[1].lower()
        if allowed_extensions and extension not in allowed_extensions:
            raise ValueError('El tipo de archivo no está permitido')

        file_storage.seek(0, 2)
        length = file_storage.tell()
        file_storage.seek(0)

        if length == 0:
            raise ValueError('El archivo está vacío')
        if max_size and length > max_size:
            raise ValueError('El archivo supera el tamaño máximo permitido')

        bucket = current_app.config['MINIO_BUCKET_NAME']
        key = f"{prefix}{uuid.uuid4()}.{extension}"
        content_type = (file_storage.content_type or 'application/octet-stream').split(';')[0].strip()

        self.client.put_object(
            bucket,
            key,
            file_storage.stream,
            length,
            content_type=content_type or 'application/octet-stream',
        )

        return key

    def get_application_file(self, object_name):
        if not self.client:
            raise RuntimeError('MinIO client not initialized')

        return self.client.get_object(current_app.config['MINIO_BUCKET_NAME'], object_name)

    def object_exists(self, key):
        if not self.client:
            return False

        try:
            self.client.stat_object(current_app.config['MINIO_BUCKET_NAME'], key)
            return True
        except S3Error as error:
            if error.code != 'NoSuchKey':
                current_app.logger.exception('No se pudo verificar un archivo de MinIO')
        except (MinioException, HTTPError, OSError):
            current_app.logger.exception('No se pudo verificar un archivo de MinIO')
        return False

    def download_response(self, key, filename, mimetype='application/octet-stream'):
        try:
            archivo = self.get_application_file(key)
        except S3Error as error:
            if error.code == 'NoSuchKey':
                abort(404)
            current_app.logger.exception('No se pudo descargar un archivo de MinIO')
            abort(503)
        except (HTTPError, OSError, RuntimeError):
            current_app.logger.exception('MinIO no disponible para descargar un archivo')
            abort(503)

        response = Response(archivo.stream(64 * 1024), mimetype=mimetype)
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.call_on_close(archivo.close)
        response.call_on_close(archivo.release_conn)
        return response

    def upload_file(self, file_data, content_type, bucket_name=None):
        if not self.client:
            raise Exception("MinIO client not initialized")

        if content_type != 'image/webp':
            raise ValueError('Solo se permiten imágenes en formato WEBP')

        bucket = bucket_name or current_app.config['MINIO_BUCKET_NAME']

        # Generar nombre único
        filename = f"{uuid.uuid4()}"
        ext = content_type.split('/')[-1] if '/' in content_type else ''
        if ext:
            filename += f".{ext}"

        # Preparar stream
        if isinstance(file_data, bytes):
            file_stream = io.BytesIO(file_data)
            length = len(file_data)
        else:
            # Asumimos que es un objeto FileStorage de Flask
            file_stream = file_data.stream
            # Mover cursor al final para obtener longitud
            file_data.seek(0, 2)
            length = file_data.tell()
            file_data.seek(0)

        self.client.put_object(
            bucket,
            filename,
            file_stream,
            length,
            content_type=content_type
        )

        return filename

    def list_objects(self, bucket_name=None):
        if not self.client:
            return []

        bucket = bucket_name or current_app.config['MINIO_BUCKET_NAME']
        return list(self.client.list_objects(bucket, recursive=True))

    def remove_object(self, object_name, bucket_name=None):
        if not self.client:
            return False

        bucket = bucket_name or current_app.config['MINIO_BUCKET_NAME']
        try:
            self.client.remove_object(bucket, object_name)
            return True
        except Exception:
            return False

    def discard_uploads(self, keys):
        for key in keys:
            if not self.remove_object(key):
                current_app.logger.warning('No se pudo retirar un archivo de una operación fallida: %s', key)

    def get_file_url(self, filename, bucket_name=None):
        """
        Construye la URL pública de un objeto en MinIO.

        Formato: {MINIO_PUBLIC_URL}/{MINIO_BUCKET_NAME}/{filename}

        MINIO_PUBLIC_URL es la URL expuesta por Traefik/proxy (con https://).
        MINIO_ENDPOINT es solo para la conexión interna de subida, nunca
        se usa para generar URLs públicas.
        """
        bucket = bucket_name or current_app.config['MINIO_BUCKET_NAME']
        public_base = (current_app.config.get('MINIO_PUBLIC_URL') or '').rstrip('/')

        if public_base:
            parsed = urlparse(public_base)
            path_parts = [part for part in parsed.path.split('/') if part]

            # Si el public_base ya incluye el bucket, no duplicarlo.
            if path_parts and path_parts[-1] == bucket:
                return f"{public_base}/{filename}"

            return f"{public_base}/{bucket}/{filename}"

        # Fallback cuando no hay MINIO_PUBLIC_URL configurada (desarrollo local).
        # Construye la URL usando el endpoint interno con el protocolo correcto.
        endpoint = current_app.config['MINIO_ENDPOINT']
        protocol = "https" if current_app.config.get('MINIO_SECURE', False) else "http"
        return f"{protocol}://{endpoint}/{bucket}/{filename}"

minio_service = MinioService()
