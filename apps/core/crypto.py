import base64
import hashlib
import json
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    raw = settings.ENCRYPTION_KEY.strip()
    if raw:
        try:
            key = raw.encode()
            Fernet(key)
            return Fernet(key)
        except Exception:
            pass
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(value: dict) -> str:
    if not value:
        return ""
    return _fernet().encrypt(json.dumps(value).encode()).decode()


def decrypt_json(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, TypeError):
        return {}
