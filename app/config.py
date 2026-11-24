import os
from dotenv import load_dotenv
from sqlalchemy import URL
from .redis_utils import build_redis_url_from_env

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = (os.environ.get(name) or '').strip().lower()
    if not value:
        return default
    if value in {'1', 'true', 'yes', 'on'}:
        return True
    if value in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'{name} debe ser un valor booleano (True o False).')


def _parse_list_from_env(name: str) -> list[str]:
    raw = os.environ.get(name)
    if raw:
        return [item.strip() for item in raw.split(',') if item.strip()]
    return []


def _database_uri():
    configured_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_URI')
    if configured_url or not os.environ.get('MARIADB_HOST'):
        return configured_url

    return URL.create(
        'mariadb+mariadbconnector',
        username=os.environ.get('MARIADB_USER'),
        password=os.environ.get('MARIADB_PASSWORD'),
        host=os.environ['MARIADB_HOST'],
        database=os.environ.get('MARIADB_DATABASE'),
    )


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY') or SECRET_KEY
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE')
    SESSION_COOKIE_SAMESITE = 'Lax'
    PROXY_FIX_X_FOR = int(os.environ.get('PROXY_FIX_X_FOR', '0'))
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    # Mail Config
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_SSL = _env_bool('MAIL_USE_SSL')
    MAIL_USE_TLS = _env_bool('MAIL_USE_TLS', default=MAIL_PORT == 587 and not MAIL_USE_SSL)
    if MAIL_USE_TLS and MAIL_USE_SSL:
        raise ValueError('Activá solo uno de MAIL_USE_TLS o MAIL_USE_SSL.')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    # MinIO Config
    MINIO_ENDPOINT = os.environ.get('MINIO_ENDPOINT', 'localhost:9000')
    MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY')
    MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY')
    MINIO_SECURE = _env_bool('MINIO_SECURE')
    MINIO_REQUIRED = _env_bool('MINIO_REQUIRED')
    MINIO_BUCKET_NAME = (
        os.environ.get('MINIO_BUCKET_NAME')
        or os.environ.get('MINIO_BUCKET')
        or 'ombudsman-uploads'
    )
    MINIO_PUBLIC_URL = (
        os.environ.get('MINIO_PUBLIC_URL')
        or os.environ.get('MINIO_PUBLIC_BASE_URL')
    )

    # Frontend URL for email links
    FRONTEND_URL = (os.environ.get('FRONTEND_URL') or 'http://localhost:5173').strip().rstrip('/')

    # Redis Settings
    REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
    REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
    REDIS_DB = os.environ.get('REDIS_DB', '0')
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
    REDIS_URL = build_redis_url_from_env(os.environ)

    # Flask-Limiter
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    CORS_ALLOWED_ORIGINS = _parse_list_from_env('CORS_ORIGINS') or [FRONTEND_URL]
