from pathlib import PurePosixPath
from urllib.parse import urlparse

from flask import abort, current_app, redirect, send_from_directory

from app.services.minio_service import minio_service


def descargar_pdf_concurso(concurso, documento_slug):
    source = concurso.document_download_source(documento_slug)
    if not source:
        abort(404)

    if source.startswith('minio:concursos/expedientes/'):
        return minio_service.download_response(
            source.removeprefix('minio:'), f'{documento_slug}.pdf', 'application/pdf',
        )

    parsed = urlparse(source)
    if parsed.scheme in {'http', 'https'} and parsed.netloc:
        return redirect(source)

    if not source.startswith('/public/'):
        abort(404)

    relative_path = source.removeprefix('/public/')
    return send_from_directory(
        current_app.static_folder, relative_path, as_attachment=True,
        download_name=PurePosixPath(relative_path).name,
    )
