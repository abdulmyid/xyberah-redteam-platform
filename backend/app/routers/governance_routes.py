"""Data governance: per-company redaction, retention, and budget settings + usage."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..auth import require_role
from ..db import get_session
from ..governance import budget_status, retention_sweep
from ..models import Company, Role, User

router = APIRouter(prefix="/api/governance", tags=["governance"])


class GovernanceIn(BaseModel):
    redact_findings: Optional[bool] = None
    retention_days: Optional[int] = None
    monthly_cost_budget: Optional[float] = None
    monthly_token_budget: Optional[int] = None
    budget_enforce: Optional[bool] = None


def _target_company(user: User, company_id: Optional[int], session: Session) -> Company:
    if user.role == Role.global_admin:
        cid = company_id if company_id is not None else user.company_id
        if cid is None:
            raise HTTPException(400, "Global admin must pass company_id")
    else:
        if company_id is not None and company_id != user.company_id:
            raise HTTPException(403, "Can only manage your own company")
        cid = user.company_id
    company = session.get(Company, cid)
    if not company:
        raise HTTPException(404, "No such company")
    return company


def _out(c: Company, session: Session) -> dict:
    return {
        "company_id": c.id, "company_name": c.name,
        "redact_findings": c.redact_findings, "retention_days": c.retention_days,
        "monthly_cost_budget": c.monthly_cost_budget, "monthly_token_budget": c.monthly_token_budget,
        "budget_enforce": c.budget_enforce,
        "usage": budget_status(session, c),
    }


@router.get("")
def get_governance(company_id: Optional[int] = None,
                   user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)):
    return _out(_target_company(user, company_id, session), session)


@router.put("")
def set_governance(body: GovernanceIn, company_id: Optional[int] = None,
                   user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)):
    c = _target_company(user, company_id, session)
    if body.redact_findings is not None:
        c.redact_findings = body.redact_findings
    if body.retention_days is not None:
        c.retention_days = max(0, body.retention_days)
    if body.monthly_cost_budget is not None:
        c.monthly_cost_budget = max(0.0, body.monthly_cost_budget)
    if body.monthly_token_budget is not None:
        c.monthly_token_budget = max(0, body.monthly_token_budget)
    if body.budget_enforce is not None:
        c.budget_enforce = body.budget_enforce
    session.add(c)
    session.commit()
    return _out(c, session)


@router.post("/retention-run")
def run_retention(user: User = Depends(require_role(Role.global_admin)),
                  session: Session = Depends(get_session)):
    return {"removed": retention_sweep(session)}
