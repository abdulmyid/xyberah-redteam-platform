"""Read the audit log and verify its integrity (company admin / global admin)."""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..audit import verify_chain
from ..auth import company_scope, require_role
from ..db import get_session
from ..models import AuditLog, Role, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(limit: int = 200, user: User = Depends(require_role(Role.company_admin)),
               session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if scope is not None:
        q = q.where(AuditLog.company_id == scope)
    return [{"id": r.id, "ts": r.ts, "user_email": r.user_email, "company_id": r.company_id,
             "method": r.method, "path": r.path, "status": r.status, "ip": r.ip}
            for r in session.exec(q).all()]


@router.get("/verify")
def verify(admin: User = Depends(require_role(Role.global_admin))):
    """Global admin: confirm the hash chain is intact (no tampering)."""
    return verify_chain()
