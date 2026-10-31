"""Scheduled (recurring) campaigns. Tenancy-scoped."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import company_scope, current_user, require_role
from ..db import get_session
from ..models import Role, Schedule, User
from ..scheduler import next_run, run_now
from ..schemas import ScheduleIn
from .campaign_routes import system_company

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _get_owned(schedule_id: int, user: User, session: Session) -> Schedule:
    sch = session.get(Schedule, schedule_id)
    scope = company_scope(user)
    if not sch or (scope is not None and sch.company_id != scope):
        raise HTTPException(404, "No such schedule")
    return sch


def _out(sch: Schedule) -> dict:
    return {
        "id": sch.id, "name": sch.name, "enabled": sch.enabled, "freq": sch.freq,
        "company_id": sch.company_id, "created_at": sch.created_at,
        "last_run_at": sch.last_run_at, "last_campaign_id": sch.last_campaign_id,
        "next_run_at": sch.next_run_at,
        "report_emails": sch.report_emails or [], "report_format": sch.report_format or "pdf",
        "target_type": (sch.template or {}).get("target", {}).get("type"),
        "campaign_name": (sch.template or {}).get("name"),
    }


@router.get("")
def list_schedules(user: User = Depends(current_user), session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(Schedule).order_by(Schedule.created_at.desc())
    if scope is not None:
        q = q.where(Schedule.company_id == scope)
    return [_out(s) for s in session.exec(q).all()]


@router.post("", status_code=201)
def create_schedule(body: ScheduleIn, user: User = Depends(require_role(Role.analyst)),
                    session: Session = Depends(get_session)):
    owner_company = user.company_id if user.company_id is not None else system_company(session).id
    sch = Schedule(
        company_id=owner_company, name=body.name, created_by=user.id,
        template=body.template.model_dump(), freq=body.freq.model_dump(),
        enabled=body.enabled, next_run_at=next_run(body.freq.model_dump()),
        report_emails=[e.strip() for e in body.report_emails if e.strip()],
        report_format=body.report_format or "pdf",
    )
    session.add(sch)
    session.commit()
    session.refresh(sch)
    return _out(sch)


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int, user: User = Depends(current_user),
                 session: Session = Depends(get_session)):
    sch = _get_owned(schedule_id, user, session)
    return {**_out(sch), "template": sch.template}


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleIn,
                    user: User = Depends(require_role(Role.analyst)),
                    session: Session = Depends(get_session)):
    sch = _get_owned(schedule_id, user, session)
    sch.name = body.name
    sch.template = body.template.model_dump()
    sch.freq = body.freq.model_dump()
    sch.enabled = body.enabled
    sch.next_run_at = next_run(body.freq.model_dump())
    sch.report_emails = [e.strip() for e in body.report_emails if e.strip()]
    sch.report_format = body.report_format or "pdf"
    session.add(sch)
    session.commit()
    session.refresh(sch)
    return _out(sch)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, user: User = Depends(require_role(Role.analyst)),
                    session: Session = Depends(get_session)):
    sch = _get_owned(schedule_id, user, session)
    session.delete(sch)
    session.commit()
    return {"ok": True}


@router.post("/{schedule_id}/run-now")
def run_schedule_now(schedule_id: int, user: User = Depends(require_role(Role.analyst)),
                     session: Session = Depends(get_session)):
    _get_owned(schedule_id, user, session)
    cid = run_now(schedule_id)
    if cid is None:
        raise HTTPException(500, "Could not start the campaign")
    return {"ok": True, "campaign_id": cid}
