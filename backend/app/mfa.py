"""Two-factor helpers: TOTP (authenticator app) and email OTP login codes."""
import hashlib
import secrets
from datetime import timedelta
from io import BytesIO

import pyotp
import qrcode
from sqlmodel import Session, select

from .crypto import decrypt, encrypt
from .models import LoginCode, User, utcnow

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5


# ---- TOTP ------------------------------------------------------------------ #
def new_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str, issuer: str = "Xyberah") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def qr_png(uri: str) -> bytes:
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify_totp(user: User, code: str) -> bool:
    if not user.totp_enabled or not user.totp_secret_enc:
        return False
    secret = decrypt(user.totp_secret_enc)
    return bool(secret) and pyotp.TOTP(secret).verify(code, valid_window=1)


def store_totp_secret(user: User, secret: str) -> None:
    user.totp_secret_enc = encrypt(secret)


# ---- Email OTP ------------------------------------------------------------- #
def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def issue_email_code(session: Session, user: User, purpose: str = "login") -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(LoginCode(user_id=user.id, code_hash=_hash(code), purpose=purpose,
                          expires_at=utcnow() + OTP_TTL))
    session.commit()
    return code  # caller emails this; never stored in plaintext


def verify_email_code(session: Session, user: User, code: str, purpose: str = "login") -> bool:
    row = session.exec(
        select(LoginCode)
        .where(LoginCode.user_id == user.id, LoginCode.purpose == purpose,
               LoginCode.consumed == False)  # noqa: E712
        .order_by(LoginCode.created_at.desc())
    ).first()
    if not row or row.expires_at < utcnow() or row.attempts >= OTP_MAX_ATTEMPTS:
        return False
    row.attempts += 1
    ok = secrets.compare_digest(row.code_hash, _hash(code))
    if ok:
        row.consumed = True
    session.add(row)
    session.commit()
    return ok


def has_2fa(user: User) -> bool:
    return user.totp_enabled or user.email_otp_enabled
