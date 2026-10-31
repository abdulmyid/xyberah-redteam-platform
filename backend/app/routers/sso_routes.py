"""SSO sign-in (OIDC + SAML) and admin configuration (config, domain maps, SCIM tokens)."""
import hashlib
import secrets
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import global_admin, set_session_cookie
from ..crypto import encrypt
from ..db import get_session
from .. import sso as sso_core
from ..models import Role, ScimToken, SsoConfig, SsoDomainMap, User, utcnow

router = APIRouter(tags=["sso"])


def _login_redirect(error: str = "") -> RedirectResponse:
    url = "/login" + (f"?sso_error={urllib.parse.quote(error)}" if error else "")
    return RedirectResponse(url=url, status_code=302)


# ---- public sign-in flows -------------------------------------------------- #
@router.get("/api/auth/sso/providers")
def sso_providers(session: Session = Depends(get_session)):
    return sso_core.providers_enabled(session)


@router.get("/api/auth/oidc/login")
def oidc_login(request: Request, session: Session = Depends(get_session)):
    try:
        url, state_jwt = sso_core.oidc_login_url(session, request)
    except HTTPException as e:
        return _login_redirect(e.detail)
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(sso_core.OIDC_STATE_COOKIE, state_jwt, httponly=True, samesite="lax",
                    secure=False, max_age=600, path="/")
    return resp


@router.get("/api/auth/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "",
                  session: Session = Depends(get_session)):
    state_cookie = request.cookies.get(sso_core.OIDC_STATE_COOKIE, "")
    if not code or not state_cookie:
        return _login_redirect("OIDC callback missing code/state")
    try:
        user = sso_core.oidc_callback(session, request, code, state, state_cookie)
    except HTTPException as e:
        return _login_redirect(str(e.detail))
    except Exception as e:  # noqa: BLE001
        return _login_redirect(f"OIDC sign-in failed: {str(e)[:150]}")
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(sso_core.OIDC_STATE_COOKIE, path="/")
    set_session_cookie(resp, user)
    return resp


@router.get("/api/auth/saml/login")
def saml_login(request: Request, session: Session = Depends(get_session)):
    try:
        return RedirectResponse(url=sso_core.saml_login_url(session, request), status_code=302)
    except HTTPException as e:
        return _login_redirect(str(e.detail))
    except Exception as e:  # noqa: BLE001
        return _login_redirect(f"SAML not available: {str(e)[:150]}")


@router.get("/api/auth/saml/metadata")
def saml_metadata(request: Request, session: Session = Depends(get_session)):
    try:
        return Response(sso_core.saml_metadata(session, request), media_type="application/xml")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"SAML metadata error: {str(e)[:200]}")


@router.post("/api/auth/saml/acs")
async def saml_acs(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    post_data = {k: v for k, v in form.items()}
    try:
        user = sso_core.saml_acs(session, request, post_data)
    except HTTPException as e:
        return _login_redirect(str(e.detail))
    except Exception as e:  # noqa: BLE001
        return _login_redirect(f"SAML sign-in failed: {str(e)[:150]}")
    resp = RedirectResponse(url="/", status_code=302)
    set_session_cookie(resp, user)
    return resp


# ---- admin configuration (global admin) ------------------------------------ #
class SsoConfigIn(BaseModel):
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""   # write-only; blank keeps existing
    oidc_scopes: str = "openid email profile"
    saml_enabled: bool = False
    saml_idp_entity_id: str = ""
    saml_idp_sso_url: str = ""
    saml_idp_x509: str = ""
    sp_base_url: str = ""
    default_role: str = "viewer"
    auto_provision: bool = True


@router.get("/api/sso/config")
def get_sso_config(user: User = Depends(global_admin), session: Session = Depends(get_session)):
    c = sso_core.get_config(session)
    return {
        "oidc_enabled": c.oidc_enabled, "oidc_issuer": c.oidc_issuer,
        "oidc_client_id": c.oidc_client_id, "oidc_secret_set": bool(c.oidc_client_secret_enc),
        "oidc_scopes": c.oidc_scopes, "saml_enabled": c.saml_enabled,
        "saml_idp_entity_id": c.saml_idp_entity_id, "saml_idp_sso_url": c.saml_idp_sso_url,
        "saml_idp_x509": c.saml_idp_x509, "sp_base_url": c.sp_base_url,
        "default_role": c.default_role, "auto_provision": c.auto_provision,
    }


@router.put("/api/sso/config")
def set_sso_config(body: SsoConfigIn, user: User = Depends(global_admin),
                   session: Session = Depends(get_session)):
    c = sso_core.get_config(session)
    c.oidc_enabled = body.oidc_enabled
    c.oidc_issuer = body.oidc_issuer.strip()
    c.oidc_client_id = body.oidc_client_id.strip()
    if body.oidc_client_secret:
        c.oidc_client_secret_enc = encrypt(body.oidc_client_secret)
    c.oidc_scopes = body.oidc_scopes.strip() or "openid email profile"
    c.saml_enabled = body.saml_enabled
    c.saml_idp_entity_id = body.saml_idp_entity_id.strip()
    c.saml_idp_sso_url = body.saml_idp_sso_url.strip()
    c.saml_idp_x509 = body.saml_idp_x509.strip()
    c.sp_base_url = body.sp_base_url.strip().rstrip("/")
    c.default_role = body.default_role
    c.auto_provision = body.auto_provision
    session.add(c)
    session.commit()
    return {"ok": True}


# ---- domain -> company maps ------------------------------------------------ #
class DomainMapIn(BaseModel):
    domain: str
    company_id: int
    default_role: str = "viewer"


@router.get("/api/sso/domains")
def list_domains(user: User = Depends(global_admin), session: Session = Depends(get_session)):
    return [{"id": d.id, "domain": d.domain, "company_id": d.company_id, "default_role": d.default_role}
            for d in session.exec(select(SsoDomainMap)).all()]


@router.post("/api/sso/domains", status_code=201)
def add_domain(body: DomainMapIn, user: User = Depends(global_admin),
               session: Session = Depends(get_session)):
    d = SsoDomainMap(domain=body.domain.strip().lower().lstrip("@"),
                     company_id=body.company_id, default_role=body.default_role)
    session.add(d)
    session.commit()
    session.refresh(d)
    return {"id": d.id, "domain": d.domain, "company_id": d.company_id, "default_role": d.default_role}


@router.delete("/api/sso/domains/{map_id}")
def del_domain(map_id: int, user: User = Depends(global_admin), session: Session = Depends(get_session)):
    d = session.get(SsoDomainMap, map_id)
    if d:
        session.delete(d)
        session.commit()
    return {"ok": True}


# ---- SCIM tokens ----------------------------------------------------------- #
class ScimTokenIn(BaseModel):
    name: str = ""
    company_id: int
    default_role: str = "viewer"


@router.get("/api/sso/scim-tokens")
def list_scim_tokens(user: User = Depends(global_admin), session: Session = Depends(get_session)):
    return [{"id": t.id, "name": t.name, "company_id": t.company_id, "default_role": t.default_role,
             "created_at": t.created_at} for t in
            session.exec(select(ScimToken).where(ScimToken.revoked == False)).all()]  # noqa: E712


@router.post("/api/sso/scim-tokens", status_code=201)
def create_scim_token(body: ScimTokenIn, user: User = Depends(global_admin),
                      session: Session = Depends(get_session)):
    raw = "scim_" + secrets.token_urlsafe(32)
    t = ScimToken(token_hash=hashlib.sha256(raw.encode()).hexdigest(), name=body.name or "SCIM",
                  company_id=body.company_id, default_role=body.default_role, created_by=user.id)
    session.add(t)
    session.commit()
    session.refresh(t)
    base = sso_core.get_config(session).sp_base_url or ""
    return {"id": t.id, "token": raw, "scim_base_url": f"{base}/scim/v2"}


@router.delete("/api/sso/scim-tokens/{token_id}")
def revoke_scim_token(token_id: int, user: User = Depends(global_admin),
                      session: Session = Depends(get_session)):
    t = session.get(ScimToken, token_id)
    if t:
        t.revoked = True
        session.add(t)
        session.commit()
    return {"ok": True}
