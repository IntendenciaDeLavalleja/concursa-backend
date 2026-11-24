import hashlib
import secrets
import string
from datetime import datetime

UNAMBIGUOUS_ALPHANUMERIC = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

def generate_random_code(length: int = 6, numeric_only: bool = True) -> str:
    """Genera un código aleatorio criptográficamente seguro."""
    if numeric_only:
        alphabet = string.digits
    else:
        alphabet = UNAMBIGUOUS_ALPHANUMERIC

    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_tracking_code() -> str:
    """Genera un código de seguimiento URL-safe: PT-YYYY-XXXXXXXX"""
    year = datetime.now().year
    suffix = generate_random_code(8, numeric_only=False)
    return f"PT-{year}-{suffix}"


def generate_verification_uid() -> str:
    """Genera un identificador URL-safe para enlaces de verificación."""
    return secrets.token_urlsafe(24)


def generate_verification_token() -> str:
    """Genera un token URL-safe para enlaces de verificación."""
    return secrets.token_urlsafe(32)


def hash_verification_token(token: str) -> str:
    """Hashea el token de verificación para no almacenarlo en texto plano."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
