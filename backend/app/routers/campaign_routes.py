"""Campaign CRUD, lifecycle control, and the live event stream. Tenancy-scoped."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ..auth import assert_same_company, company_scope, current_user, require_role
from ..db import get_session
from ..models import Campaign, Company, Finding, Role, User
from ..orchestrator import runner
from ..orchestrator.events import bus
from ..orchestrator.targets import Target, missing_keys
from ..reports.aggregate import summarize
from ..schemas import CampaignIn

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _get_owned(campaign_id: int, user: User, session: Session) -> Campaign:
    c = session.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such campaign")
    assert_same_company(user, c.company_id)
    return c


def _out(c: Campaign, session: Session, with_summary: bool = False) -> dict:
    target = Target(**c.target)
    data = {
        "id": c.id, "name": c.name, "description": c.description, "status": c.status,
        "company_id": c.company_id, "target_display": target.display,
        "tools": c.tools, "stages": c.stages, "created_at": c.created_at,
        "started_at": c.started_at, "finished_at": c.finished_at, "error": c.error,
    }
    if with_summary:
        findings = session.exec(select(Finding).where(Finding.campaign_id == c.id)).all()
        data["summary"] = summarize([f.model_dump() for f in findings])
    return data


@router.get("")
def list_campaigns(user: User = Depends(current_user), session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(Campaign).order_by(Campaign.created_at.desc())
    if scope is not None:
        q = q.where(Campaign.company_id == scope)
    return [_out(c, session, with_summary=True) for c in session.exec(q).all()]


@router.post("", status_code=201)
def create_campaign(body: CampaignIn, user: User = Depends(require_role(Role.analyst)),
                    session: Session = Depends(get_session)):
    if user.company_id is None:
        raise HTTPException(400, "Global admins must act within a company to create campaigns")
    missing = missing_keys(body.target)
    campaign = Campaign(company_id=user.company_id, name=body.name, description=body.description,
                        created_by=user.id, target=body.target.model_dump(),
                        tools={**body.tools.model_dump(), "purpose": body.tools.purpose})
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return {**_out(campaign, session), "warnings": [f"{k} is not set" for k in missing]}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    return _out(_get_owned(campaign_id, user, session), session, with_summary=True)


@router.post("/{campaign_id}/start")
def start(campaign_id: int, user: User = Depends(require_role(Role.analyst)),
          session: Session = Depends(get_session)):
    c = _get_owned(campaign_id, user, session)
    if c.status in ("running", "queued"):
        raise HTTPException(409, "Campaign is already running")
    running = session.exec(select(Campaign).where(Campaign.company_id == c.company_id,
                                                  Campaign.status == "running")).all()
    company = session.get(Company, c.company_id)
    if company and len(running) >= company.max_concurrent_campaigns:
        raise HTTPException(429, "Company concurrent campaign limit reached")
    c.status = "queued"
    c.stages = []
    c.error = ""
    session.add(c)
    session.commit()
    runner.start_campaign(c.id)
    return {"ok": True, "status": "queued"}


@router.post("/{campaign_id}/pause")
def pause(campaign_id: int, user: User = Depends(require_role(Role.analyst)),
          session: Session = Depends(get_session)):
    c = _get_owned(campaign_id, user, session)
    if c.status != "running":
        raise HTTPException(409, "Only a running campaign can be paused")
    runner.request_pause(c.id)
    return {"ok": True, "note": "Will pause after the current stage finishes"}


@router.post("/{campaign_id}/resume")
def resume(campaign_id: int, user: User = Depends(require_role(Role.analyst)),
           session: Session = Depends(get_session)):
    c = _get_owned(campaign_id, user, session)
    if c.status != "paused":
        raise HTTPException(409, "Campaign is not paused")
    runner.request_resume(c.id)
    return {"ok": True}


@router.post("/{campaign_id}/stop")
def stop(campaign_id: int, user: User = Depends(require_role(Role.analyst)),
         session: Session = Depends(get_session)):
    c = _get_owned(campaign_id, user, session)
    runner.request_stop(c.id)
    return {"ok": True}


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, user: User = Depends(require_role(Role.analyst)),
                    session: Session = Depends(get_session)):
    c = _get_owned(campaign_id, user, session)
    if runner.is_running(c.id):
        raise HTTPException(409, "Stop the campaign before deleting it")
    for f in session.exec(select(Finding).where(Finding.campaign_id == c.id)).all():
        session.delete(f)
    session.delete(c)
    session.commit()
    return {"ok": True}


@router.get("/{campaign_id}/findings")
def findings(campaign_id: int, user: User = Depends(current_user),
             session: Session = Depends(get_session)):
    _get_owned(campaign_id, user, session)
    rows = session.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()
    return [f.model_dump() for f in rows]


@router.get("/{campaign_id}/events")
async def events(campaign_id: int, request: Request, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    _get_owned(campaign_id, user, session)

    async def stream():
        for ev in bus.history(campaign_id):
            yield f"data: {json.dumps(ev)}\n\n"
        q = bus.subscribe(campaign_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(campaign_id, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
