# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS base
RUN python -m pip install --no-cache-dir pip==26.3

FROM base AS dependencies
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libmariadb-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN python -m venv --without-pip /opt/venv \
    && python -m pip --python /opt/venv install --no-cache-dir --no-binary=mariadb -r requirements.txt \
    && python -m pip --python /opt/venv check

FROM base
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc_dir \
    FLASK_DEBUG=0 \
    SESSION_COOKIE_SECURE=True \
    PROXY_FIX_X_FOR=1 \
    MINIO_REQUIRED=True \
    TZ=America/Montevideo
WORKDIR /app
# Debian Bookworm incluye la corrección de CVE-2026-44172 en libmariadb3.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libmariadb3)" ge '1:10.11.18-0+deb12u1' \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home app
COPY --from=dependencies /opt/venv /opt/venv
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY public/ ./public/
COPY wsgi.py entrypoint.sh ./
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 755 /app/entrypoint.sh
USER app
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=4 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:5000/health', timeout=3).close()"]
ENTRYPOINT ["/app/entrypoint.sh"]
