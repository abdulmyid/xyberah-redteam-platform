"""Alert channels (Slack / Teams / webhook) and a test-send. Tenancy-scoped;
managed by company admins (and global admins)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import company_scope, require_role
from ..crypto import decrypt, encrypt
from ..db import get_session
from ..models import NotifyChannel, Role, User
from ..notify import send_test

router = APIRouter(prefix="/api/notify", tags=["notify"])
_KINDS = {"slack", "teams", "webhook"}


class ChannelIn(BaseModel):
    name: str = ""
    kind: str = "webhook"
    url: str = ""
    on_complete: bool = True
    min_risk: int = 0
    enabled: bool = True


class TestIn(BaseModel):
    kind: str = "webhook"
    url: str = ""


def _out(ch: NotifyChannel) -> dict:
    url = decrypt(ch.url_enc) or ""
    masked = url[:28] + "…" if len(url) > 30 else url
    return {"id": ch.id, "name": ch.name, "kind": ch.kind, "url_preview": masked,
            "on_complete": ch.on_complete, "min_risk": ch.min_risk, "enabled": ch.enabled}


def _owned(cid: int, user: User, session: Session) -> NotifyChannel:
    ch = session.get(NotifyChannel, cid)
    scope = company_scope(user)
    if not ch or (scope is not None and ch.company_id != scope):
        raise HTTPException(404, "No such channel")
    return ch


@router.get("/channels")
def list_channels(user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(NotifyChannel)
    if scope is not None:
        q = q.where(NotifyChannel.company_id == scope)
    return [_out(c) for c in session.exec(q).all()]


@router.post("/channels", status_code=201)
def create_channel(body: ChannelIn, user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)):
    if body.kind not in _KINDS:
        raise HTTPException(422, "Invalid channel kind")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "URL must be http(s)")
    ch = NotifyChannel(company_id=user.company_id, name=body.name or body.kind, kind=body.kind,
                       url_enc=encrypt(body.url), on_complete=body.on_complete,
                       min_risk=body.min_risk, enabled=body.enabled, created_by=user.id)
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return _out(ch)


@router.put("/channels/{cid}")
def update_channel(cid: int, body: ChannelIn, user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)):
    ch = _owned(cid, user, session)
    ch.name = body.name or ch.name
    if body.kind in _KINDS:
        ch.kind = body.kind
    if body.url:
        if not body.url.startswith(("http://", "https://")):
            raise HTTPException(422, "URL must be http(s)")
        ch.url_enc = encrypt(body.url)
    ch.on_complete = body.on_complete
    ch.min_risk = body.min_risk
    ch.enabled = body.enabled
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return _out(ch)


@router.delete("/channels/{cid}")
def delete_channel(cid: int, user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)):
    ch = _owned(cid, user, session)
    session.delete(ch)
    session.commit()
    return {"ok": True}


@router.post("/test")
def test_channel(body: TestIn, user: User = Depends(require_role(Role.company_admin))):
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "URL must be http(s)")
    return send_test(body.kind, body.url)


class BaseUrlIn(BaseModel):
    url: str = ""


@router.get("/base-url")
def get_base_url(user: User = Depends(require_role(Role.company_admin)),
                 session: Session = Depends(get_session)):
    from ..models import Setting
    row = session.get(Setting, "public_base_url")
    return {"url": row.value if row and isinstance(row.value, str) else ""}


@router.put("/base-url")
def set_base_url(body: BaseUrlIn, user: User = Depends(require_role(Role.global_admin)),
                 session: Session = Depends(get_session)):
    from ..models import Setting
    row = session.get(Setting, "public_base_url")
    if row:
        row.value = body.url
    else:
        row = Setting(key="public_base_url", value=body.url)
    session.add(row)
    session.commit()
    return {"ok": True, "url": body.url}
