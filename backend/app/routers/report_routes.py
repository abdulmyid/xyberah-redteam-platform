"""Report generation (HTML/PDF/JSON/CSV) and shareable read-only links."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from sqlmodel import Session, select

from ..auth import assert_same_company, current_user
from ..db import get_session
from ..models import Campaign, Finding, ShareLink, User, utcnow
from ..orchestrator.targets import Target
from ..reports import builder

router = APIRouter(prefix="/api", tags=["reports"])

_MEDIA = {"pdf": "application/pdf", "json": "application/json", "csv": "text/csv"}


def _load(campaign_id: int, session: Session):
    c = session.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such campaign")
    findings = [f.model_dump() for f in
                session.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()]
    tools_used = sorted({f["tool"] for f in findings})
    return c, findings, tools_used, Target(**c.target).display


def _render(fmt: str, campaign, findings, tools_used, target_display):
    html = builder.render_html(campaign, findings, tools_used, target_display)
    if fmt == "html":
        return HTMLResponse(html)
    if fmt == "pdf":
        return Response(builder.render_pdf(html), media_type=_MEDIA["pdf"],
                        headers={"Content-Disposition": f'attachment; filename="{campaign.name}.pdf"'})
    if fmt == "json":
        return Response(builder.render_json(campaign, findings, target_display), media_type=_MEDIA["json"])
    if fmt == "csv":
        return Response(builder.render_csv(findings), media_type=_MEDIA["csv"],
                        headers={"Content-Disposition": f'attachment; filename="{campaign.name}.csv"'})
    raise HTTPException(400, "format must be html, pdf, json or csv")


@router.get("/campaigns/{campaign_id}/report.{fmt}")
def report(campaign_id: int, fmt: str, user: User = Depends(current_user),
           session: Session = Depends(get_session)):
    c, findings, tools_used, target_display = _load(campaign_id, session)
    assert_same_company(user, c.company_id)
    return _render(fmt, c, findings, tools_used, target_display)


# ---- share links ----------------------------------------------------------- #
@router.post("/campaigns/{campaign_id}/share", status_code=201)
def create_share(campaign_id: int, days: int = 7, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    c = session.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(404, "No such campaign")
    assert_same_company(user, c.company_id)
    token = secrets.token_urlsafe(24)
    session.add(ShareLink(token=token, company_id=c.company_id, campaign_id=campaign_id,
                          created_by=user.id, expires_at=utcnow() + timedelta(days=days)))
    session.commit()
    return {"token": token, "url": f"/shared/{token}"}


@router.delete("/share/{token}")
def revoke_share(token: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    link = session.get(ShareLink, token)
    if not link:
        raise HTTPException(404, "No such link")
    assert_same_company(user, link.company_id)
    link.revoked = True
    session.add(link)
    session.commit()
    return {"ok": True}


@router.get("/shared/{token}.{fmt}")
def shared_report(token: str, fmt: str, session: Session = Depends(get_session)):
    """Public, unauthenticated read-only report via share token."""
    link = session.get(ShareLink, token)
    if not link or link.revoked or (link.expires_at and link.expires_at < utcnow()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link is invalid or expired")
    c, findings, tools_used, target_display = _load(link.campaign_id, session)
    return _render(fmt, c, findings, tools_used, target_display)
