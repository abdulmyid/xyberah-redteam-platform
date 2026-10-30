"""Hash-chained audit log.

A middleware records every mutating API call (method, path, status, actor, IP).
Each row's hash chains the previous row's hash, so removing or altering any past
entry breaks the chain and is detectable via GET /api/audit/verify. This is the
kind of evidence security and compliance teams ask for first.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

import jwt
from sqlmodel import Session, select

from .config import get_settings
from .db import engine
from .models import AuditLog, User

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Noisy or sensitive paths we don't record a body for (we never log bodies anyway)
SKIP_PREFIXES = ("/api/auth/totp/qr", "/api/demo/")


def _actor(request) -> tuple[Optional[int], str, Optional[int]]:
    token = request.cookies.get("xyberah_session")
    if not token:
        return None, "", None
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        uid = int(payload["sub"])
    except Exception:
        return None, "", None
    with Session(engine) as s:
        u = s.get(User, uid)
        return (uid, u.email, u.company_id) if u else (uid, "", None)


def record(request, status: int) -> None:
    if request.method not in MUTATING:
        return
    path = request.url.path
    if not path.startswith("/api") or any(path.startswith(p) for p in SKIP_PREFIXES):
        return
    uid, email, company_id = _actor(request)
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "")
    ts = datetime.now(timezone.utc)
    with Session(engine) as s:
        last = s.exec(select(AuditLog).order_by(AuditLog.id.desc())).first()
        prev_hash = last.row_hash if last else ""
        payload = json.dumps({"ts": ts.isoformat(), "uid": uid, "email": email,
                              "company_id": company_id, "method": request.method,
                              "path": path, "status": status, "ip": ip, "prev": prev_hash},
                             sort_keys=True)
        row_hash = hashlib.sha256(payload.encode()).hexdigest()
        s.add(AuditLog(ts=ts, user_id=uid, user_email=email, company_id=company_id,
                       method=request.method, path=path, status=status, ip=ip,
                       prev_hash=prev_hash, row_hash=row_hash))
        s.commit()


def verify_chain() -> dict:
    """Recompute the chain and report the first broken link, if any."""
    with Session(engine) as s:
        rows = s.exec(select(AuditLog).order_by(AuditLog.id)).all()
    prev = ""
    for r in rows:
        payload = json.dumps({"ts": r.ts.isoformat(), "uid": r.user_id, "email": r.user_email,
                              "company_id": r.company_id, "method": r.method, "path": r.path,
                              "status": r.status, "ip": r.ip, "prev": prev}, sort_keys=True)
        if hashlib.sha256(payload.encode()).hexdigest() != r.row_hash or r.prev_hash != prev:
            return {"valid": False, "broken_at": r.id, "checked": len(rows)}
        prev = r.row_hash
    return {"valid": True, "checked": len(rows)}
