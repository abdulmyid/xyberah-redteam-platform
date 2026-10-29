"""Company, user and invite management.

- Companies: global admin only.
- Users / invites: company admins manage their own company; global admins any.
- SMTP: global admin only.
"""
import hashlib
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from ..auth import (assert_same_company, company_scope, current_user, global_admin,
                    hash_password, require_role)
from ..db import get_session
from ..email_service import get_smtp, save_email_settings_or_422, send_email
from ..models import (Company, CompanyBranding, Invite, Role, User, utcnow)
from ..schemas import CompanyIn, InviteIn, RoleUpdateIn, SmtpIn

router = APIRouter(prefix="/api", tags=["admin"])


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"


# ---- companies (global admin) --------------------------------------------- #
@router.get("/companies")
def list_companies(admin: User = Depends(global_admin), session: Session = Depends(get_session)):
    out = []
    for c in session.exec(select(Company)).all():
        users = len(session.exec(select(User).where(User.company_id == c.id)).all())
        out.append({"id": c.id, "name": c.name, "slug": c.slug, "disabled": c.disabled,
                    "users": users, "max_users": c.max_users,
                    "max_concurrent_campaigns": c.max_concurrent_campaigns})
    return out


@router.post("/companies", status_code=201)
def create_company(body: CompanyIn, admin: User = Depends(global_admin),
                   session: Session = Depends(get_session)):
    slug = body.slug or _slug(body.name)
    if session.exec(select(Company).where((Company.name == body.name) | (Company.slug == slug))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Company name or slug already exists")
    c = Company(name=body.name, slug=slug, max_users=body.max_users,
                max_concurrent_campaigns=body.max_concurrent_campaigns)
    session.add(c)
    session.commit()
    session.refresh(c)
    return {"id": c.id, "name": c.name, "slug": c.slug}


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyIn, admin: User = Depends(global_admin),
                   session: Session = Depends(get_session)):
    c = session.get(Company, company_id)
    if not c:
        raise HTTPException(404, "No such company")
    c.name, c.max_users = body.name, body.max_users
    c.max_concurrent_campaigns = body.max_concurrent_campaigns
    session.add(c)
    session.commit()
    return {"ok": True}


@router.post("/companies/{company_id}/disable")
def toggle_company(company_id: int, disabled: bool = True, admin: User = Depends(global_admin),
                   session: Session = Depends(get_session)):
    c = session.get(Company, company_id)
    if not c:
        raise HTTPException(404, "No such company")
    c.disabled = disabled
    session.add(c)
    session.commit()
    return {"ok": True, "disabled": disabled}


# ---- users ----------------------------------------------------------------- #
@router.get("/users")
def list_users(user: User = Depends(require_role(Role.company_admin)),
               session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(User)
    if scope is not None:
        q = q.where(User.company_id == scope)
    return [{"id": u.id, "email": u.email, "username": u.username, "role": u.role,
             "company_id": u.company_id, "disabled": u.disabled,
             "totp_enabled": u.totp_enabled, "last_login": u.last_login}
            for u in session.exec(q).all()]


@router.patch("/users/{user_id}/role")
def set_role(user_id: int, body: RoleUpdateIn, actor: User = Depends(require_role(Role.company_admin)),
             session: Session = Depends(get_session)):
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(404, "No such user")
    assert_same_company(actor, target.company_id)
    if body.role == Role.global_admin and actor.role != Role.global_admin:
        raise HTTPException(403, "Only a global admin can grant global admin")
    if target.id == actor.id:
        raise HTTPException(400, "You cannot change your own role")
    target.role = body.role
    session.add(target)
    session.commit()
    return {"ok": True}


@router.post("/users/{user_id}/disable")
def disable_user(user_id: int, disabled: bool = True,
                 actor: User = Depends(require_role(Role.company_admin)),
                 session: Session = Depends(get_session)):
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(404, "No such user")
    assert_same_company(actor, target.company_id)
    if target.id == actor.id:
        raise HTTPException(400, "You cannot disable your own account")
    target.disabled = disabled
    session.add(target)
    session.commit()
    return {"ok": True, "disabled": disabled}


# ---- invites --------------------------------------------------------------- #
@router.get("/invites")
def list_invites(user: User = Depends(require_role(Role.company_admin)),
                 session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(Invite).where(Invite.accepted_at == None)  # noqa: E711
    if scope is not None:
        q = q.where(Invite.company_id == scope)
    return [{"id": i.id, "email": i.email, "role": i.role, "company_id": i.company_id,
             "expires_at": i.expires_at, "created_at": i.created_at}
            for i in session.exec(q).all()]


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, request: Request,
                  actor: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    # Company admins may only invite into their own company and not grant global admin
    if actor.role == Role.global_admin:
        company_id = body.company_id
    else:
        company_id = actor.company_id
        if body.role in (Role.global_admin,):
            raise HTTPException(403, "You cannot grant that role")
    if company_id is None and body.role != Role.global_admin:
        raise HTTPException(400, "A company is required for this role")

    if company_id is not None:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(404, "No such company")
        count = len(session.exec(select(User).where(User.company_id == company_id)).all())
        if count >= company.max_users:
            raise HTTPException(400, f"Company user limit ({company.max_users}) reached")
    if session.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(409, "A user with this email already exists")

    token = secrets.token_urlsafe(32)
    inv = Invite(token_hash=hashlib.sha256(token.encode()).hexdigest(), email=body.email,
                 company_id=company_id, role=body.role, invited_by=actor.id,
                 expires_at=utcnow() + timedelta(days=7))
    session.add(inv)
    session.commit()

    base = str(request.base_url).rstrip("/")
    link = f"{base}/invite/{token}"
    delivery = _send_invite(body.email, link, actor.username)
    return {"ok": True, "invite_url": link, "delivery": delivery}


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: int, actor: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)):
    inv = session.get(Invite, invite_id)
    if not inv:
        raise HTTPException(404, "No such invite")
    if actor.role != Role.global_admin and inv.company_id != actor.company_id:
        raise HTTPException(404, "No such invite")
    session.delete(inv)
    session.commit()
    return {"ok": True}


# ---- SMTP (global admin) --------------------------------------------------- #
@router.get("/smtp")
def smtp_get(admin: User = Depends(global_admin)):
    return get_smtp()


@router.put("/smtp")
def smtp_put(body: SmtpIn, admin: User = Depends(global_admin)):
    return save_email_settings_or_422(body.model_dump(exclude_none=True))


@router.post("/smtp/test")
def smtp_test(to: str, admin: User = Depends(global_admin)):
    return send_email(to, "Xyberah SMTP test",
                      "<p>This is a test email from Xyberah. SMTP is working.</p>")


def _send_invite(email: str, link: str, inviter: str) -> dict:
    html = (f"<p>{inviter} invited you to Xyberah, the AI red-teaming platform.</p>"
            f"<p><a href='{link}'>Accept your invitation</a> (valid for 7 days).</p>"
            f"<p>Or paste this link:<br>{link}</p>")
    try:
        return send_email(email, "You're invited to Xyberah", html)
    except Exception as exc:
        return {"delivered": "failed", "error": str(exc)}
