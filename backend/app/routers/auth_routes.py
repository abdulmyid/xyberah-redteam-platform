import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import Response as RawResponse
from sqlmodel import Session, select

from .. import mfa
from ..auth import (clear_session_cookie, current_user, hash_password, mfa_token,
                    set_session_cookie, throttle, user_from_mfa_token, validate_new_password,
                    verify_password)
from ..db import get_session
from ..email_service import send_email
from ..models import Invite, Role, User, utcnow
from ..schemas import (AcceptInviteIn, LoginIn, MfaVerifyIn, PasswordChangeIn, SetupIn, TotpEnableIn)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public_user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "username": u.username, "role": u.role,
            "company_id": u.company_id, "totp_enabled": u.totp_enabled,
            "email_otp_enabled": u.email_otp_enabled}


# ---- first-run setup ------------------------------------------------------- #
@router.get("/setup-status")
def setup_status(session: Session = Depends(get_session)):
    """Public. True only before the first (global admin) account exists."""
    exists = session.exec(select(User)).first() is not None
    return {"needs_setup": not exists}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, response: Response, session: Session = Depends(get_session)):
    """Create the first global admin. Works ONLY while no users exist, so it
    cannot be used to seize an initialized instance."""
    if session.exec(select(User)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")
    validate_new_password(body.password)
    user = User(email=body.email, username=body.username or body.email,
                company_id=None, role=Role.global_admin,
                password_hash=hash_password(body.password), last_login=utcnow())
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, user)  # auto sign-in
    return {"user": _public_user(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    ip = request.client.host if request.client else "?"
    key = f"{body.email}:{ip}"
    throttle.check(key)
    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or user.disabled or not verify_password(body.password, user.password_hash):
        throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    throttle.reset(key)

    if mfa.has_2fa(user):
        if user.email_otp_enabled:
            code = mfa.issue_email_code(session, user, "login")
            _send_login_code(user, code)
        return {"mfa_required": True, "mfa_token": mfa_token(user),
                "methods": [m for m, on in (("totp", user.totp_enabled),
                                            ("email", user.email_otp_enabled)) if on]}
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    set_session_cookie(response, user)
    return {"mfa_required": False, "user": _public_user(user)}


@router.post("/login/mfa")
def login_mfa(body: MfaVerifyIn, response: Response, session: Session = Depends(get_session)):
    user = user_from_mfa_token(body.mfa_token, session)
    ok = (mfa.verify_totp(user, body.code) if body.method == "totp"
          else mfa.verify_email_code(session, user, body.code, "login"))
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code")
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    set_session_cookie(response, user)
    return {"user": _public_user(user)}


@router.post("/logout")
def logout(response: Response, user: User = Depends(current_user)):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _public_user(user)


@router.post("/password")
def change_password(body: PasswordChangeIn, user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    validate_new_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    session.add(user)
    session.commit()
    return {"ok": True}


# ---- TOTP setup ------------------------------------------------------------ #
@router.post("/totp/begin")
def totp_begin(user: User = Depends(current_user)):
    secret = mfa.new_totp_secret()
    uri = mfa.provisioning_uri(secret, user.email)
    return {"secret": secret, "otpauth_uri": uri}


@router.get("/totp/qr")
def totp_qr(secret: str, user: User = Depends(current_user)):
    uri = mfa.provisioning_uri(secret, user.email)
    return RawResponse(content=mfa.qr_png(uri), media_type="image/png")


@router.post("/totp/enable")
def totp_enable(body: TotpEnableIn, user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    import pyotp

    if not pyotp.TOTP(body.secret).verify(body.code, valid_window=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code did not match; try again")
    mfa.store_totp_secret(user, body.secret)
    user.totp_enabled = True
    session.add(user)
    session.commit()
    return {"ok": True, "totp_enabled": True}


@router.post("/totp/disable")
def totp_disable(user: User = Depends(current_user), session: Session = Depends(get_session)):
    user.totp_enabled = False
    user.totp_secret_enc = ""
    session.add(user)
    session.commit()
    return {"ok": True}


@router.post("/email-otp/{action}")
def email_otp_toggle(action: str, user: User = Depends(current_user),
                     session: Session = Depends(get_session)):
    if action not in ("enable", "disable"):
        raise HTTPException(400, "action must be enable or disable")
    user.email_otp_enabled = action == "enable"
    session.add(user)
    session.commit()
    return {"ok": True, "email_otp_enabled": user.email_otp_enabled}


# ---- invite acceptance (public) ------------------------------------------- #
@router.get("/invite/{token}")
def invite_info(token: str, session: Session = Depends(get_session)):
    inv = _valid_invite(token, session)
    return {"email": inv.email, "role": inv.role, "company_id": inv.company_id}


@router.post("/invite/accept")
def accept_invite(body: AcceptInviteIn, session: Session = Depends(get_session)):
    inv = _valid_invite(body.token, session)
    if session.exec(select(User).where(User.email == inv.email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    validate_new_password(body.password)
    user = User(email=inv.email, username=body.username, company_id=inv.company_id,
                role=inv.role, password_hash=hash_password(body.password))
    inv.accepted_at = utcnow()
    session.add(user)
    session.add(inv)
    session.commit()
    return {"ok": True}


def _valid_invite(token: str, session: Session) -> Invite:
    th = hashlib.sha256(token.encode()).hexdigest()
    inv = session.exec(select(Invite).where(Invite.token_hash == th)).first()
    if not inv or inv.accepted_at or inv.expires_at < utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite is invalid or expired")
    return inv


def _send_login_code(user: User, code: str) -> None:
    html = (f"<p>Your {('Xyberah')} sign-in code is:</p>"
            f"<p style='font-size:22px;font-weight:700;letter-spacing:3px'>{code}</p>"
            f"<p>It expires in 10 minutes. If you didn't try to sign in, ignore this email.</p>")
    try:
        send_email(user.email, "Your Xyberah sign-in code", html)
    except Exception:
        pass  # never block login on email transport errors; code is also in dev outbox
