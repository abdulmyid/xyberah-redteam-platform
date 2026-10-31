"""Hash-chained audit log.

A middleware records every mutating API call (method, path, status, actor, IP).
Each row's hash chains the previous row's hash, so removing or altering any past
entry breaks the chain and is detectable via GET /api/audit/verify. This is the
kind of evidence security and compliance teams ask for first.
"""
import hashlib
import json
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from sqlmodel import Session, select

from .config import get_settings
from .db import engine
from .models import AuditLog, Setting, User

log = logging.getLogger("xyberah.audit")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SYSLOG_KEY = "syslog"
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
    _syslog_emit({"ts": ts.isoformat(), "email": email, "method": request.method,
                  "path": path, "status": status, "ip": ip, "company_id": company_id})


# ---- syslog push ----------------------------------------------------------- #
def get_syslog() -> dict[str, Any]:
    with Session(engine) as s:
        row = s.get(Setting, SYSLOG_KEY)
    cfg = dict(row.value) if row and row.value else {}
    return {"enabled": bool(cfg.get("enabled")), "host": cfg.get("host", ""),
            "port": int(cfg.get("port", 514)), "protocol": cfg.get("protocol", "udp")}


def save_syslog(values: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as s:
        row = s.get(Setting, SYSLOG_KEY)
        cur = dict(row.value) if row and row.value else {}
        for k in ("enabled", "host", "port", "protocol"):
            if values.get(k) is not None:
                cur[k] = values[k]
        if row:
            row.value = cur
        else:
            row = Setting(key=SYSLOG_KEY, value=cur)
        s.add(row)
        s.commit()
    return get_syslog()


def _cef_line(ev: dict) -> str:
    sev = 3 if (ev.get("status") or 0) < 400 else 6
    ext = (f"src={ev.get('ip','')} suser={ev.get('email','')} "
           f"act={ev.get('method','')} request={ev.get('path','')} "
           f"outcome={ev.get('status','')} cs1Label=company cs1={ev.get('company_id','')}")
    # RFC3164-ish PRI (facility 13 = log audit, severity 6 = info)
    return f"<110>{ev.get('ts','')} xyberah CEF:0|Xyberah|AuditLog|1.0|audit|{ev.get('method','')} {ev.get('path','')}|{sev}|{ext}"


def _syslog_emit(ev: dict) -> None:
    cfg = get_syslog()
    if not cfg["enabled"] or not cfg["host"]:
        return
    msg = _cef_line(ev).encode()[:2000]
    try:
        if cfg["protocol"] == "tcp":
            with socket.create_connection((cfg["host"], cfg["port"]), timeout=2) as sock:
                sock.sendall(msg + b"\n")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(msg, (cfg["host"], cfg["port"]))
    except Exception as exc:  # best-effort; never break a request
        log.debug("syslog emit failed: %s", exc)


def syslog_test(cfg: dict[str, Any]) -> dict[str, Any]:
    ev = {"ts": datetime.now(timezone.utc).isoformat(), "email": "test@xyberah",
          "method": "TEST", "path": "/api/ops/syslog/test", "status": 200, "ip": "127.0.0.1", "company_id": ""}
    msg = _cef_line(ev).encode()
    try:
        if cfg.get("protocol") == "tcp":
            with socket.create_connection((cfg["host"], int(cfg.get("port", 514))), timeout=3) as sock:
                sock.sendall(msg + b"\n")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(msg, (cfg["host"], int(cfg.get("port", 514))))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


# ---- rotation -------------------------------------------------------------- #
def rotate(before_days: int) -> dict:
    """Archive audit rows older than N days to a JSONL file, delete them, and
    re-anchor the remaining chain so integrity verification still passes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, before_days))
    with Session(engine) as s:
        old = s.exec(select(AuditLog).where(AuditLog.ts < cutoff).order_by(AuditLog.id)).all()
        if not old:
            return {"archived": 0, "remaining": _count(s)}
        arch_dir = get_settings().data_dir / "audit_archive"
        arch_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        fpath = arch_dir / f"audit-{stamp}.jsonl"
        with fpath.open("w", encoding="utf-8") as f:
            for r in old:
                f.write(json.dumps({"id": r.id, "ts": r.ts.isoformat(), "user_email": r.user_email,
                                    "company_id": r.company_id, "method": r.method, "path": r.path,
                                    "status": r.status, "ip": r.ip, "row_hash": r.row_hash}) + "\n")
        for r in old:
            s.delete(r)
        s.commit()
        # Re-anchor remaining rows (recompute the chain from prev="").
        remaining = s.exec(select(AuditLog).order_by(AuditLog.id)).all()
        prev = ""
        for r in remaining:
            payload = json.dumps({"ts": r.ts.isoformat(), "uid": r.user_id, "email": r.user_email,
                                  "company_id": r.company_id, "method": r.method, "path": r.path,
                                  "status": r.status, "ip": r.ip, "prev": prev}, sort_keys=True)
            r.prev_hash = prev
            r.row_hash = hashlib.sha256(payload.encode()).hexdigest()
            prev = r.row_hash
            s.add(r)
        s.commit()
        return {"archived": len(old), "file": str(fpath), "remaining": len(remaining)}


def _count(s: Session) -> int:
    from sqlalchemy import func
    return s.exec(select(func.count()).select_from(AuditLog)).one()


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
