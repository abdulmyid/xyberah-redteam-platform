"""Minimal SCIM 2.0 user provisioning. An IdP (Okta/Entra) authenticates with a
SCIM bearer token (scoped to one company) and can create / update / deactivate
users. Enough of the spec for the common IdP sync flows."""
import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Role, ScimToken, User, utcnow

router = APIRouter(prefix="/scim/v2", tags=["scim"])
SCIM_MEDIA = "application/scim+json"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"


def scim_ctx(request: Request, session: Session = Depends(get_session)) -> ScimToken:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing SCIM token")
    row = session.exec(select(ScimToken).where(
        ScimToken.token_hash == hashlib.sha256(token.encode()).hexdigest())).first()
    if not row or row.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid SCIM token")
    return row


def _user_resource(u: User, request: Request) -> dict:
    return {
        "schemas": [USER_SCHEMA],
        "id": str(u.id),
        "userName": u.email,
        "externalId": u.external_id or None,
        "name": {"formatted": u.username},
        "emails": [{"value": u.email, "primary": True}],
        "active": not u.disabled,
        "meta": {"resourceType": "User", "location": f"{str(request.base_url).rstrip('/')}/scim/v2/Users/{u.id}"},
    }


def _scim(data: dict, code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=code, media_type=SCIM_MEDIA)


def _extract_email(body: dict) -> str:
    email = (body.get("userName") or "").strip().lower()
    if "@" not in email:
        for e in body.get("emails") or []:
            if isinstance(e, dict) and e.get("value"):
                email = str(e["value"]).strip().lower()
                if e.get("primary"):
                    break
    return email


@router.get("/Users")
def list_users(request: Request, filter: str = "", startIndex: int = 1, count: int = 100,
               ctx: ScimToken = Depends(scim_ctx), session: Session = Depends(get_session)):
    q = select(User).where(User.company_id == ctx.company_id)
    m = re.search(r'userName\s+eq\s+"([^"]+)"', filter or "", re.I)
    if m:
        q = q.where(User.email == m.group(1).strip().lower())
    rows = session.exec(q).all()
    page = rows[startIndex - 1: startIndex - 1 + count]
    return _scim({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(rows), "startIndex": startIndex, "itemsPerPage": len(page),
        "Resources": [_user_resource(u, request) for u in page],
    })


@router.post("/Users")
async def create_user(request: Request, ctx: ScimToken = Depends(scim_ctx),
                      session: Session = Depends(get_session)):
    body = await request.json()
    email = _extract_email(body)
    if not email or "@" not in email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "userName/email required")
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        # SCIM: 409 on duplicate
        return _scim({"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                      "detail": "User already exists", "status": "409"}, code=409)
    try:
        role = Role(ctx.default_role or "viewer")
    except ValueError:
        role = Role.viewer
    name = (body.get("name") or {}).get("formatted") or body.get("displayName") or email
    u = User(email=email, username=name, company_id=ctx.company_id, role=role,
             auth_provider="scim", external_id=str(body.get("externalId") or ""),
             disabled=not body.get("active", True), password_hash="", last_login=None)
    session.add(u)
    session.commit()
    session.refresh(u)
    return _scim(_user_resource(u, request), code=201)


def _owned(user_id: int, ctx: ScimToken, session: Session) -> User:
    u = session.get(User, user_id)
    if not u or u.company_id != ctx.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


@router.get("/Users/{user_id}")
def get_user(user_id: int, request: Request, ctx: ScimToken = Depends(scim_ctx),
             session: Session = Depends(get_session)):
    return _scim(_user_resource(_owned(user_id, ctx, session), request))


@router.put("/Users/{user_id}")
async def replace_user(user_id: int, request: Request, ctx: ScimToken = Depends(scim_ctx),
                       session: Session = Depends(get_session)):
    u = _owned(user_id, ctx, session)
    body = await request.json()
    if body.get("name", {}).get("formatted"):
        u.username = body["name"]["formatted"]
    if "active" in body:
        u.disabled = not body["active"]
    u.external_id = str(body.get("externalId") or u.external_id)
    session.add(u)
    session.commit()
    session.refresh(u)
    return _scim(_user_resource(u, request))


@router.patch("/Users/{user_id}")
async def patch_user(user_id: int, request: Request, ctx: ScimToken = Depends(scim_ctx),
                     session: Session = Depends(get_session)):
    u = _owned(user_id, ctx, session)
    body = await request.json()
    for op in body.get("Operations", []):
        path = (op.get("path") or "").lower()
        value = op.get("value")
        # Okta/Entra deactivate: {op:replace, value:{active:false}} or path=active
        if isinstance(value, dict) and "active" in value:
            u.disabled = not value["active"]
        elif path == "active":
            u.disabled = not (value if isinstance(value, bool) else str(value).lower() == "true")
    session.add(u)
    session.commit()
    session.refresh(u)
    return _scim(_user_resource(u, request))


@router.delete("/Users/{user_id}", status_code=204)
def delete_user(user_id: int, ctx: ScimToken = Depends(scim_ctx),
                session: Session = Depends(get_session)):
    u = _owned(user_id, ctx, session)
    u.disabled = True  # deactivate rather than hard-delete (preserve audit/findings links)
    session.add(u)
    session.commit()
    return JSONResponse({}, status_code=204)
