from os.path import isfile
from pathlib import PurePosixPath
from urllib.parse import urlparse

from flask import abort, current_app, redirect, send_from_directory
from werkzeug.utils import safe_join

from app.services.minio_service import minio_service


MINIO_PDF_PREFIX = 'minio:concursos/expedientes/'
PUBLIC_FILE_PREFIX = '/public/'


def _es_enlace_externo(source):
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def pdf_concurso_disponible(source):
    if source.startswith(MINIO_PDF_PREFIX):
        return minio_service.object_exists(source.removeprefix('minio:'))
    if source.startswith(PUBLIC_FILE_PREFIX):
        path = safe_join(current_app.static_folder, source.removeprefix(PUBLIC_FILE_PREFIX))
        return path is not None and isfile(path)
    return _es_enlace_externo(source)


def descargar_pdf_concurso(concurso, documento_slug):
    source = concurso.document_download_source(documento_slug)
    if not source:
        abort(404)

    if source.startswith(MINIO_PDF_PREFIX):
        return minio_service.download_response(
            source.removeprefix('minio:'), f'{documento_slug}.pdf', 'application/pdf',
        )

    if _es_enlace_externo(source):
        return redirect(source)

    if not source.startswith(PUBLIC_FILE_PREFIX):
        abort(404)

    relative_path = source.removeprefix(PUBLIC_FILE_PREFIX)
    return send_from_directory(
        current_app.static_folder, relative_path, as_attachment=True,
        download_name=PurePosixPath(relative_path).name,
    )
