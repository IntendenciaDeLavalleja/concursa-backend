#!/bin/sh
set -eu
: "${SECRET_KEY:?Configurá SECRET_KEY para iniciar el backend}"
: "${FRONTEND_URL:?Configurá FRONTEND_URL con el origen del portal público}"
: "${MAIL_SERVER:?Configurá MAIL_SERVER con el servidor SMTP}"
: "${MAIL_DEFAULT_SENDER:?Configurá MAIL_DEFAULT_SENDER con el remitente SMTP}"

# Prometheus requiere un directorio limpio en cada arranque de Gunicorn.
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
find "$PROMETHEUS_MULTIPROC_DIR" -maxdepth 1 -type f -name '*.db' -delete

echo "Aplicando migraciones de la base de datos..."
flask --app 'app:create_app()' db upgrade

exec gunicorn --no-control-socket --bind 0.0.0.0:5000 --workers "${GUNICORN_WORKERS:-4}" \
    --worker-class gthread --threads 2 'app:create_app()'
