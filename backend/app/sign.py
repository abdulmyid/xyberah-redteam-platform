"""Tamper-evident signing for attestation reports. The signature is an HMAC over a
canonical digest of the report content, keyed by the instance secret, so anyone with
this instance can verify a report was produced here and has not been altered."""
import hashlib
import hmac
import json
from typing import Any

from .config import get_settings


def content_hash(obj: Any) -> str:
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(canon).hexdigest()


def sign(digest_hex: str) -> str:
    key = ("xyberah-attest:" + get_settings().secret_key).encode()
    return hmac.new(key, digest_hex.encode(), hashlib.sha256).hexdigest()


def verify(digest_hex: str, signature: str) -> bool:
    try:
        return hmac.compare_digest(sign(digest_hex), signature)
    except Exception:
        return False
