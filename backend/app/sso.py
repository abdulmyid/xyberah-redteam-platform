"""SSO core: OIDC + SAML sign-in and domain-based JIT provisioning.

OIDC uses httpx + PyJWT (PyJWKClient) — no extra deps. SAML uses python3-saml
(onelogin), imported lazily so the module still loads if it is not installed yet.
"""
import base64
import hashlib
import os
import secrets
from typing import Any, Optional

import httpx
import jwt
from fastapi import HTTPException, Request, status
from sqlmodel import Session, select

from .config import get_settings
from .crypto import decrypt
from .models import Role, SsoConfig, SsoDomainMap, User, utcnow

OIDC_STATE_COOKIE = "xyberah_oidc"


# ---- config ---------------------------------------------------------------- #
def get_config(session: Session) -> SsoConfig:
    cfg = session.get(SsoConfig, 1)
    if not cfg:
        cfg = SsoConfig(id=1)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def providers_enabled(session: Session) -> dict[str, bool]:
    cfg = get_config(session)
    return {"oidc": bool(cfg.oidc_enabled and cfg.oidc_issuer and cfg.oidc_client_id),
            "saml": bool(cfg.saml_enabled and cfg.saml_idp_sso_url and cfg.saml_idp_x509)}


# ---- JIT provisioning ------------------------------------------------------ #
def provision(session: Session, email: str, name: str, provider: str, external_id: str) -> User:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SSO assertion had no email")
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        if user.disabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
        if external_id and not user.external_id:
            user.external_id = external_id
            user.auth_provider = provider
        user.last_login = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    cfg = get_config(session)
    if not cfg.auto_provision:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Auto-provisioning is off; ask an admin to create your account")
    domain = email.split("@")[-1]
    dm = session.exec(select(SsoDomainMap).where(SsoDomainMap.domain == domain)).first()
    if not dm:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"No company is mapped to the domain '{domain}'")
    try:
        role = Role(dm.default_role or cfg.default_role or "viewer")
    except ValueError:
        role = Role.viewer
    user = User(email=email, username=name or email, company_id=dm.company_id, role=role,
                auth_provider=provider, external_id=external_id, password_hash="",
                last_login=utcnow())
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---- OIDC ------------------------------------------------------------------ #
def _redirect_uri(cfg: SsoConfig, request: Request) -> str:
    base = (cfg.sp_base_url or "").rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/oidc/callback"


def _discover(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=10) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def oidc_login_url(session: Session, request: Request) -> tuple[str, str]:
    """Return (authorization_url, state_jwt). The caller sets state_jwt as a cookie."""
    cfg = get_config(session)
    if not providers_enabled(session)["oidc"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OIDC is not configured")
    disc = _discover(cfg.oidc_issuer)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "response_type": "code", "client_id": cfg.oidc_client_id,
        "redirect_uri": _redirect_uri(cfg, request), "scope": cfg.oidc_scopes or "openid email profile",
        "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    import urllib.parse
    url = disc["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
    state_jwt = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier, "kind": "oidc",
         "exp": utcnow().timestamp() + 600},
        get_settings().secret_key, algorithm="HS256")
    return url, state_jwt


def oidc_callback(session: Session, request: Request, code: str, state: str, state_cookie: str) -> User:
    cfg = get_config(session)
    try:
        st = jwt.decode(state_cookie, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SSO state expired; try again")
    if st.get("kind") != "oidc" or not secrets.compare_digest(st.get("state", ""), state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SSO state mismatch")
    disc = _discover(cfg.oidc_issuer)
    data = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": _redirect_uri(cfg, request), "client_id": cfg.oidc_client_id,
        "code_verifier": st["verifier"],
    }
    secret = decrypt(cfg.oidc_client_secret_enc) if cfg.oidc_client_secret_enc else ""
    if secret:
        data["client_secret"] = secret
    with httpx.Client(timeout=15) as c:
        r = c.post(disc["token_endpoint"], data=data,
                   headers={"Accept": "application/json"})
        if r.status_code >= 400:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token exchange failed: {r.text[:200]}")
        tok = r.json()
    id_token = tok.get("id_token")
    if not id_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No id_token returned")
    jwks = jwt.PyJWKClient(disc["jwks_uri"])
    signing_key = jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, signing_key.key, algorithms=["RS256", "ES256"],
                        audience=cfg.oidc_client_id, issuer=disc.get("issuer", cfg.oidc_issuer))
    if claims.get("nonce") and not secrets.compare_digest(claims["nonce"], st.get("nonce", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC nonce mismatch")
    email = claims.get("email") or claims.get("preferred_username", "")
    name = claims.get("name") or claims.get("given_name", "") or email
    return provision(session, email, name, "oidc", str(claims.get("sub", "")))


# ---- SAML (python3-saml, lazily imported) ---------------------------------- #
def _saml_settings(cfg: SsoConfig, request: Request) -> dict[str, Any]:
    base = (cfg.sp_base_url or "").rstrip("/") or str(request.base_url).rstrip("/")
    return {
        "strict": True, "debug": False,
        "sp": {
            "entityId": f"{base}/api/auth/saml/metadata",
            "assertionConsumerService": {"url": f"{base}/api/auth/saml/acs",
                                         "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"},
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {
            "entityId": cfg.saml_idp_entity_id or cfg.saml_idp_sso_url,
            "singleSignOnService": {"url": cfg.saml_idp_sso_url,
                                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"},
            "x509cert": cfg.saml_idp_x509,
        },
    }


def _saml_req(request: Request, post_data: Optional[dict] = None) -> dict[str, Any]:
    url = request.url
    return {
        "https": "on" if url.scheme == "https" else "off",
        "http_host": url.hostname or "",
        "server_port": str(url.port or (443 if url.scheme == "https" else 80)),
        "script_name": url.path,
        "get_data": dict(request.query_params),
        "post_data": post_data or {},
    }


def _saml_auth(cfg: SsoConfig, request: Request, post_data: Optional[dict] = None):
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # lazy: needs python3-saml + xmlsec
    return OneLogin_Saml2_Auth(_saml_req(request, post_data), _saml_settings(cfg, request))


def saml_login_url(session: Session, request: Request) -> str:
    cfg = get_config(session)
    if not providers_enabled(session)["saml"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML is not configured")
    return _saml_auth(cfg, request).login()


def saml_metadata(session: Session, request: Request) -> str:
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    cfg = get_config(session)
    settings = OneLogin_Saml2_Settings(_saml_settings(cfg, request), sp_validation_only=True)
    return settings.get_sp_metadata().decode() if isinstance(settings.get_sp_metadata(), bytes) \
        else settings.get_sp_metadata()


def saml_acs(session: Session, request: Request, post_data: dict) -> User:
    cfg = get_config(session)
    auth = _saml_auth(cfg, request, post_data)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"SAML error: {', '.join(errors)}")
    if not auth.is_authenticated():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "SAML assertion not authenticated")
    attrs = auth.get_attributes()
    nameid = auth.get_nameid()

    def _first(*keys: str) -> str:
        for k in keys:
            v = attrs.get(k)
            if v:
                return v[0] if isinstance(v, list) else str(v)
        return ""
    email = _first("email", "mail", "emailAddress",
                   "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or nameid
    name = _first("displayName", "name", "cn",
                  "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name") or email
    return provision(session, email, name, "saml", nameid or email)
