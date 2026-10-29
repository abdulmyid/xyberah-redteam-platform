"""Authentication, RBAC and tenancy enforcement.

Login is two-step when the user has 2FA enabled:
  1. POST /login (email+password) -> {mfa_required: true, mfa_token}
  2. POST /login/mfa (mfa_token + TOTP or email code) -> session cookie
The mfa_token is a short-lived JWT that only authorizes step 2.

Session is a JWT in an HttpOnly, SameSite=Lax cookie. State-changing requests
must also send `X-Requested-With: xyberah` (CSRF defense).
"""
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session
from .models import ROLE_RANK, Company, Role, User

COOKIE = "xyberah_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# ---- passwords ------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bool(hashed) and bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def validate_new_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 10 characters")


# ---- tokens ---------------------------------------------------------------- #
def _encode(claims: dict, minutes: Optional[int] = None, hours: Optional[int] = None) -> str:
    exp = datetime.now(timezone.utc) + (timedelta(minutes=minutes) if minutes else timedelta(hours=hours or 1))
    return jwt.encode({**claims, "exp": exp}, get_settings().secret_key, algorithm="HS256")


def _decode(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])


def set_session_cookie(response: Response, user: User) -> None:
    s = get_settings()
    token = _encode({"sub": str(user.id), "kind": "session"}, hours=s.session_hours)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_hours * 3600, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def mfa_token(user: User) -> str:
    return _encode({"sub": str(user.id), "kind": "mfa"}, minutes=10)


def user_from_mfa_token(token: str, session: Session) -> User:
    try:
        payload = _decode(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA challenge expired")
    if payload.get("kind") != "mfa":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA token")
    user = session.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


# ---- current user + RBAC --------------------------------------------------- #
def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = _decode(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    if payload.get("kind") != "session":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    user = session.get(User, int(payload["sub"]))
    if not user or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    if user.company_id is not None:
        company = session.get(Company, user.company_id)
        if company and company.disabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Company is disabled")
    if request.method not in SAFE_METHODS and request.headers.get("x-requested-with") != "xyberah":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Requested-With header")
    return user


def require_role(minimum: Role):
    """Dependency: user must be at least `minimum` within their company.
    Global admins satisfy every requirement."""

    def dep(user: User = Depends(current_user)) -> User:
        if user.role == Role.global_admin:
            return user
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum.value} or higher")
        return user

    return dep


def global_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.global_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Global admin only")
    return user


# ---- tenancy helpers ------------------------------------------------------- #
def company_scope(user: User) -> Optional[int]:
    """The company_id a query should be filtered by. None means 'all' (global admin)."""
    return None if user.role == Role.global_admin else user.company_id


def assert_same_company(user: User, row_company_id: int) -> None:
    if user.role == Role.global_admin:
        return
    if user.company_id != row_company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")  # don't leak existence


# ---- throttle -------------------------------------------------------------- #
class LoginThrottle:
    def __init__(self, limit: int = 10, window: int = 900) -> None:
        self.limit, self.window = limit, window
        self.failures: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        self.failures[key] = [t for t in self.failures[key] if now - t < self.window]
        if len(self.failures[key]) >= self.limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try later")

    def fail(self, key: str) -> None:
        self.failures[key].append(time.time())

    def reset(self, key: str) -> None:
        self.failures.pop(key, None)


throttle = LoginThrottle()


def bootstrap_global_admin(session: Session) -> None:
    """Create the first global admin from XYBERAH_ADMIN_* when no users exist."""
    if session.exec(select(User)).first():
        return
    s = get_settings()
    if not s.admin_password:
        raise RuntimeError("No users yet: set XYBERAH_ADMIN_PASSWORD to create the first global admin")
    validate_new_password(s.admin_password)
    email = s.admin_username if "@" in s.admin_username else f"{s.admin_username}@local"
    session.add(User(email=email, username=s.admin_username, company_id=None,
                     role=Role.global_admin, password_hash=hash_password(s.admin_password)))
    session.commit()
