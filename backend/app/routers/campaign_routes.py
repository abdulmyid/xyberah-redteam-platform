"""Campaign CRUD, lifecycle control, and the live event stream. Tenancy-scoped."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ..auth import assert_same_company, company_scope, current_user, require_role
from ..db import get_session
from ..models import Campaign, Company, Finding, PromptSet, Role, User

SYSTEM_COMPANY_SLUG = "__system__"


def system_company(session: Session) -> Company:
    """Hidden company that owns global-admin campaigns (which have no company)."""
    c = session.exec(select(Company).where(Company.slug == SYSTEM_COMPANY_SLUG)).first()
    if not c:
        c = Company(name="Global (system)", slug=SYSTEM_COMPANY_SLUG, max_concurrent_campaigns=99)
        session.add(c)
        session.commit()
        session.refresh(c)
    return c
from ..orchestrator import runner
from ..orchestrator.events import bus
from ..orchestrator.targets import Target, missing_keys
from ..reports.aggregate import summarize
from ..schemas import BulkFindingIn, CampaignIn, FindingUpdateIn

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
    # Global admins have no company of their own; their campaigns live under the
    # hidden system company so they can scan without restriction.
    owner_company = user.company_id if user.company_id is not None else system_company(session).id
    missing = missing_keys(body.target)
    tools = {**body.tools.model_dump(), "purpose": body.tools.purpose}
    # Snapshot a selected prompt-set library entry into the campaign so the run is
    # reproducible even if the set is later edited or deleted.
    if tools.get("custom") and tools.get("prompt_set_id") and not tools.get("custom_prompts"):
        ps = session.get(PromptSet, tools["prompt_set_id"])
        scope = company_scope(user)
        if not ps or (scope is not None and ps.company_id != scope):
            raise HTTPException(404, "No such prompt set")
        tools["custom_prompts"] = ps.prompts or []
        tools["custom_grading"] = ps.grading or {}
    campaign = Campaign(company_id=owner_company, name=body.name, description=body.description,
                        created_by=user.id, target=body.target.model_dump(), tools=tools)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return {**_out(campaign, session), "warnings": [f"{k} is not set" for k in missing]}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    return _out(_get_owned(campaign_id, user, session), session, with_summary=True)


@router.post("/{campaign_id}/duplicate", status_code=201)
def duplicate_campaign(campaign_id: int, saved_target_id: int | None = None,
                       user: User = Depends(require_role(Role.analyst)),
                       session: Session = Depends(get_session)):
    """Clone a campaign's config into a new draft (same tools), keeping the original
    target or swapping to a saved target. Enables A/B: run identical prompts against
    a raw model and a guardrail-protected endpoint, then compare with the drift diff."""
    c = _get_owned(campaign_id, user, session)
    target = dict(c.target)
    suffix = "(copy)"
    if saved_target_id is not None:
        from ..crypto import decrypt
        from ..models import SavedTarget
        import json as _json
        st = session.get(SavedTarget, saved_target_id)
        scope = company_scope(user)
        if not st or (scope is not None and st.company_id != scope):
            raise HTTPException(404, "No such saved target")
        target = _json.loads(decrypt(st.config_enc))
        suffix = f"(vs {st.name})"
    new = Campaign(company_id=c.company_id, name=f"{c.name} {suffix}", description=c.description,
                   created_by=user.id, target=target, tools=dict(c.tools), status="draft")
    session.add(new)
    session.commit()
    session.refresh(new)
    return _out(new, session)


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
    if company and company.budget_enforce:
        from ..governance import budget_status
        bs = budget_status(session, company)
        if bs["over_budget"]:
            raise HTTPException(429, "Monthly budget exceeded for this company; "
                                     "raise the budget or disable enforcement to continue")
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
def findings(campaign_id: int, status: str | None = None, severity: str | None = None,
             tool: str | None = None, passed: str | None = None, q: str | None = None,
             sort: str = "severity", offset: int = 0, limit: int = 100,
             user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Filtered, sorted, paginated findings. Returns {items, total, offset, limit}."""
    from sqlalchemy import case, func, or_
    _get_owned(campaign_id, user, session)
    conds = [Finding.campaign_id == campaign_id]
    if status:
        conds.append(Finding.status == status)
    if severity:
        conds.append(Finding.severity == severity)
    if tool:
        conds.append(Finding.tool == tool)
    if passed in ("true", "false"):
        conds.append(Finding.passed == (passed == "true"))
    if q:
        like = f"%{q}%"
        conds.append(or_(Finding.prompt.like(like), Finding.plugin.like(like),
                         Finding.reason.like(like), Finding.output.like(like),
                         Finding.category.like(like)))
    total = session.exec(select(func.count()).select_from(Finding).where(*conds)).one()
    sev_order = case((Finding.severity == "critical", 0), (Finding.severity == "high", 1),
                     (Finding.severity == "medium", 2), (Finding.severity == "low", 3), else_=9)
    base = select(Finding).where(*conds)
    base = base.order_by(Finding.plugin) if sort == "plugin" else base.order_by(sev_order, Finding.score.desc())
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = session.exec(base.offset(offset).limit(limit)).all()
    return {"items": [f.model_dump() for f in rows], "total": total, "offset": offset, "limit": limit}


@router.post("/{campaign_id}/findings/bulk")
def bulk_update_findings(campaign_id: int, body: BulkFindingIn,
                         user: User = Depends(require_role(Role.analyst)),
                         session: Session = Depends(get_session)):
    _get_owned(campaign_id, user, session)
    if body.status is not None and body.status not in _FINDING_STATUSES:
        raise HTTPException(422, "Invalid status")
    if not body.ids:
        return {"updated": 0}
    from ..models import utcnow
    rows = session.exec(select(Finding).where(Finding.campaign_id == campaign_id,
                                              Finding.id.in_(body.ids))).all()
    for f in rows:
        if body.status is not None:
            f.status = body.status
        if body.assignee_id is not None:
            f.assignee_id = body.assignee_id or None
        if body.triage_note is not None:
            f.triage_note = body.triage_note[:8000]
        f.updated_at = utcnow()
        f.updated_by = user.id
        session.add(f)
    session.commit()
    return {"updated": len(rows)}


_FINDING_STATUSES = {"open", "triaged", "fixed", "accepted_risk", "false_positive"}


@router.patch("/{campaign_id}/findings/{finding_id}")
def update_finding(campaign_id: int, finding_id: int, body: FindingUpdateIn,
                   user: User = Depends(require_role(Role.analyst)),
                   session: Session = Depends(get_session)):
    _get_owned(campaign_id, user, session)
    f = session.get(Finding, finding_id)
    if not f or f.campaign_id != campaign_id:
        raise HTTPException(404, "No such finding")
    if body.status is not None:
        if body.status not in _FINDING_STATUSES:
            raise HTTPException(422, "Invalid status")
        f.status = body.status
    if body.assignee_id is not None:
        f.assignee_id = body.assignee_id or None
    if body.triage_note is not None:
        f.triage_note = body.triage_note[:8000]
    from ..models import utcnow
    f.updated_at = utcnow()
    f.updated_by = user.id
    session.add(f)
    session.commit()
    session.refresh(f)
    return f.model_dump()


@router.post("/{campaign_id}/findings/{finding_id}/retest")
def retest_finding(campaign_id: int, finding_id: int,
                   user: User = Depends(require_role(Role.analyst)),
                   session: Session = Depends(get_session)):
    _get_owned(campaign_id, user, session)
    f = session.get(Finding, finding_id)
    if not f or f.campaign_id != campaign_id:
        raise HTTPException(404, "No such finding")
    if not f.prompt:
        raise HTTPException(422, "This finding has no prompt to retest")
    result = runner.retest_single(campaign_id, f.prompt)
    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "Retest failed"))
    from ..models import utcnow
    f.retest_output = str(result.get("output", ""))[:8000]
    f.retest_passed = result.get("passed")
    f.retested_at = utcnow()
    # If it was graded and now passes, nudge status toward fixed (user can override)
    if result.get("graded") and result.get("passed") and f.status in ("open", "triaged"):
        f.status = "fixed"
    f.updated_at = utcnow()
    f.updated_by = user.id
    session.add(f)
    session.commit()
    session.refresh(f)
    return f.model_dump()


@router.post("/{campaign_id}/findings/{finding_id}/ticket")
def create_finding_ticket(campaign_id: int, finding_id: int, config_id: int | None = None,
                          user: User = Depends(require_role(Role.analyst)),
                          session: Session = Depends(get_session)):
    """File an issue-tracker ticket for one finding and link it back."""
    import json as _json
    from ..crypto import decrypt
    from ..models import TicketConfig
    from ..ticketing import create_ticket
    c = _get_owned(campaign_id, user, session)
    f = session.get(Finding, finding_id)
    if not f or f.campaign_id != campaign_id:
        raise HTTPException(404, "No such finding")
    scope = company_scope(user)
    q = select(TicketConfig).where(TicketConfig.enabled == True)  # noqa: E712
    if config_id:
        q = q.where(TicketConfig.id == config_id)
    if scope is not None:
        q = q.where(TicketConfig.company_id == scope)
    cfg = session.exec(q).first()
    if not cfg:
        raise HTTPException(400, "No ticket integration is configured (Settings → Ticketing)")
    conf = _json.loads(decrypt(cfg.config_enc) or "{}")
    res = create_ticket(cfg.kind, conf, f, c)
    if not res.get("ok"):
        raise HTTPException(502, res.get("error", "Ticket creation failed"))
    from ..models import utcnow
    f.ticket_url = res.get("url", "")
    f.ticket_key = res.get("key", "")
    f.updated_at = utcnow()
    f.updated_by = user.id
    session.add(f)
    session.commit()
    session.refresh(f)
    return f.model_dump()


def _finding_key(f: Finding) -> str:
    return f"{f.tool}|{f.plugin}|{(f.prompt or '')[:200]}"


@router.get("/{campaign_id}/diff")
def diff(campaign_id: int, against: int, user: User = Depends(current_user),
         session: Session = Depends(get_session)):
    """Compare this campaign's failing findings with another run (e.g. a previous
    scan of the same target) to surface regressions and fixes."""
    cur = _get_owned(campaign_id, user, session)
    base = _get_owned(against, user, session)
    cur_f = session.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()
    base_f = session.exec(select(Finding).where(Finding.campaign_id == against)).all()
    cur_fail = {_finding_key(f): f for f in cur_f if not f.passed}
    base_fail = {_finding_key(f): f for f in base_f if not f.passed}

    def _brief(f: Finding) -> dict:
        return {"id": f.id, "severity": f.severity, "plugin": f.plugin,
                "category": f.category, "tool": f.tool, "prompt": (f.prompt or "")[:300]}

    new = [_brief(f) for k, f in cur_fail.items() if k not in base_fail]
    fixed = [_brief(f) for k, f in base_fail.items() if k not in cur_fail]
    persisting = [_brief(f) for k, f in cur_fail.items() if k in base_fail]
    cur_sum = summarize([f.model_dump() for f in cur_f])
    base_sum = summarize([f.model_dump() for f in base_f])
    return {
        "current": {"id": cur.id, "name": cur.name, "finished_at": cur.finished_at,
                    "risk_score": cur_sum["risk_score"], "failed": cur_sum["failed"]},
        "baseline": {"id": base.id, "name": base.name, "finished_at": base.finished_at,
                     "risk_score": base_sum["risk_score"], "failed": base_sum["failed"]},
        "risk_delta": cur_sum["risk_score"] - base_sum["risk_score"],
        "new": new, "fixed": fixed, "persisting": persisting,
        "counts": {"new": len(new), "fixed": len(fixed), "persisting": len(persisting)},
    }


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
