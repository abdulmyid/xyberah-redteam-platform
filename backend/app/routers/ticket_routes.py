"""Issue-tracker (GitHub / Jira) integration config. Tenancy-scoped; company admins."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import company_scope, require_role
from ..crypto import decrypt, encrypt
from ..db import get_session
from ..models import Role, TicketConfig, User
from ..ticketing import test_config

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
_KINDS = {"github", "jira"}
_SEV = {"critical", "high", "medium", "low"}


class ConfigIn(BaseModel):
    name: str = ""
    kind: str = "github"
    config: dict = {}
    enabled: bool = True
    auto_create: bool = False
    min_severity: str = "high"


class TestIn(BaseModel):
    kind: str = "github"
    config: dict = {}


def _safe_config(kind: str, conf: dict) -> dict:
    """Non-secret fields only (never return the token)."""
    if kind == "github":
        return {"repo": conf.get("repo", "")}
    if kind == "jira":
        return {"base_url": conf.get("base_url", ""), "project_key": conf.get("project_key", ""),
                "email": conf.get("email", ""), "issue_type": conf.get("issue_type", "Bug")}
    return {}


def _out(t: TicketConfig) -> dict:
    conf = json.loads(decrypt(t.config_enc) or "{}")
    return {"id": t.id, "name": t.name, "kind": t.kind, "enabled": t.enabled,
            "auto_create": t.auto_create, "min_severity": t.min_severity,
            "config": _safe_config(t.kind, conf)}


def _owned(cid: int, user: User, session: Session) -> TicketConfig:
    t = session.get(TicketConfig, cid)
    scope = company_scope(user)
    if not t or (scope is not None and t.company_id != scope):
        raise HTTPException(404, "No such ticket config")
    return t


@router.get("/configs")
def list_configs(user: User = Depends(require_role(Role.company_admin)),
                 session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(TicketConfig)
    if scope is not None:
        q = q.where(TicketConfig.company_id == scope)
    return [_out(t) for t in session.exec(q).all()]


@router.post("/configs", status_code=201)
def create_config(body: ConfigIn, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    if body.kind not in _KINDS:
        raise HTTPException(422, "kind must be github or jira")
    if body.min_severity not in _SEV:
        raise HTTPException(422, "invalid min_severity")
    t = TicketConfig(company_id=user.company_id, name=body.name or body.kind, kind=body.kind,
                     config_enc=encrypt(json.dumps(body.config)), enabled=body.enabled,
                     auto_create=body.auto_create, min_severity=body.min_severity, created_by=user.id)
    session.add(t)
    session.commit()
    session.refresh(t)
    return _out(t)


@router.put("/configs/{cid}")
def update_config(cid: int, body: ConfigIn, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    t = _owned(cid, user, session)
    if body.kind in _KINDS:
        t.kind = body.kind
    t.name = body.name or t.name
    t.enabled = body.enabled
    t.auto_create = body.auto_create
    if body.min_severity in _SEV:
        t.min_severity = body.min_severity
    # Merge: keep the existing token if the new config omits it (blank).
    if body.config:
        existing = json.loads(decrypt(t.config_enc) or "{}")
        merged = {**existing, **{k: v for k, v in body.config.items() if v != ""}}
        t.config_enc = encrypt(json.dumps(merged))
    session.add(t)
    session.commit()
    session.refresh(t)
    return _out(t)


@router.delete("/configs/{cid}")
def delete_config(cid: int, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    t = _owned(cid, user, session)
    session.delete(t)
    session.commit()
    return {"ok": True}


@router.post("/test")
def test(body: TestIn, user: User = Depends(require_role(Role.company_admin))):
    if body.kind not in _KINDS:
        raise HTTPException(422, "kind must be github or jira")
    return test_config(body.kind, body.config)
