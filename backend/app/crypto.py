"""Symmetric encryption for secrets at rest (TOTP seeds, SMTP password).

Key is derived from the instance secret key, so secrets in the DB are useless
without the data volume's .secret_key. Not a substitute for a real KMS, but far
better than storing seeds and passwords in plaintext.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("xyberah-secrets:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""
