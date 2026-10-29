"""Custom TLS certificate management for the frontend proxy.

The proxy (Caddy) serves an auto self-signed cert by default. A global admin can
upload their company's own certificate + private key here; we validate that the
key matches the cert and that the chain is PEM, then write them to the shared
certs volume. The proxy's watcher picks up the change and reloads, switching
from the self-signed cert to the uploaded one. Removing them reverts to
self-signed.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from .config import get_settings


def _certs_dir() -> Path:
    d = get_settings().certs_dir / "custom"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _crt_path() -> Path:
    return _certs_dir() / "tls.crt"


def _key_path() -> Path:
    return _certs_dir() / "tls.key"


def status() -> dict[str, Any]:
    crt = _crt_path()
    if not crt.exists() or not _key_path().exists():
        return {"mode": "self_signed", "custom": False}
    try:
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        return {
            "mode": "custom", "custom": True,
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "not_after": cert.not_valid_after_utc.isoformat(),
            "expired": cert.not_valid_after_utc < datetime.now(timezone.utc),
            "sans": _sans(cert),
        }
    except Exception:
        return {"mode": "custom", "custom": True, "warning": "certificate could not be parsed"}


def _sans(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        return []


def install(cert_pem: bytes, key_pem: bytes) -> dict[str, Any]:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except Exception:
        raise HTTPException(422, "Certificate is not valid PEM")
    try:
        key = serialization.load_pem_private_key(key_pem, password=None)
    except Exception:
        raise HTTPException(422, "Private key is not valid PEM (must be unencrypted)")
    if not _key_matches_cert(cert, key):
        raise HTTPException(422, "Private key does not match the certificate")
    if cert.not_valid_after_utc < datetime.now(timezone.utc):
        raise HTTPException(422, "Certificate has already expired")

    _crt_path().write_bytes(cert_pem)
    _key_path().write_bytes(key_pem)
    _key_path().chmod(0o600)
    return status()


def remove() -> dict[str, Any]:
    for p in (_crt_path(), _key_path()):
        if p.exists():
            p.unlink()
    return status()


def _key_matches_cert(cert: x509.Certificate, key: Any) -> bool:
    """True if the private key corresponds to the certificate's public key."""
    cert_pub = cert.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    key_pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return cert_pub == key_pub
