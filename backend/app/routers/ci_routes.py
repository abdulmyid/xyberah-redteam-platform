"""CI/CD: API tokens and a headless scan endpoint with a pass/fail quality gate."""
import hashlib
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import api_token_user, company_scope, require_role
from ..crypto import decrypt
from ..db import get_session
from ..models import ApiToken, Campaign, Finding, Role, SavedTarget, User, utcnow
from ..orchestrator import runner
from ..orchestrator.targets import Target
from ..reports.aggregate import summarize
from ..schemas import CampaignIn

router = APIRouter(prefix="/api", tags=["ci"])


# ---- token management (session-authenticated, shown in Settings) ----------- #
class TokenIn(BaseModel):
    name: str = ""


@router.get("/tokens")
def list_tokens(user: User = Depends(require_role(Role.analyst)), session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(ApiToken).where(ApiToken.revoked == False)  # noqa: E712
    if scope is not None:
        q = q.where(ApiToken.company_id == scope)
    return [{"id": t.id, "name": t.name, "created_at": t.created_at, "last_used": t.last_used}
            for t in session.exec(q).all()]


@router.post("/tokens", status_code=201)
def create_token(body: TokenIn, user: User = Depends(require_role(Role.analyst)),
                 session: Session = Depends(get_session)):
    raw = "xyb_" + secrets.token_urlsafe(32)
    row = ApiToken(token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                   name=body.name or "ci-token", company_id=user.company_id, created_by=user.id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "name": row.name, "token": raw}  # shown once


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, user: User = Depends(require_role(Role.analyst)),
                 session: Session = Depends(get_session)):
    row = session.get(ApiToken, token_id)
    if not row or (user.role != Role.global_admin and row.company_id != user.company_id):
        raise HTTPException(404, "No such token")
    row.revoked = True
    session.add(row)
    session.commit()
    return {"ok": True}


# ---- CI scan (bearer-token authenticated) ---------------------------------- #
class Gate(BaseModel):
    max_risk_score: Optional[int] = None
    max_failures: Optional[int] = None
    max_critical: Optional[int] = None
    max_high: Optional[int] = None


class CiScanIn(BaseModel):
    name: str = "CI scan"
    saved_target_id: Optional[int] = None
    target: Optional[Target] = None
    tools: Optional[dict[str, Any]] = None
    gate: Gate = Gate()


def _gate_result(summary: dict, gate: dict) -> dict:
    reasons = []
    g = gate or {}
    if g.get("max_risk_score") is not None and summary["risk_score"] > g["max_risk_score"]:
        reasons.append(f"risk_score {summary['risk_score']} > {g['max_risk_score']}")
    if g.get("max_failures") is not None and summary["failed"] > g["max_failures"]:
        reasons.append(f"failures {summary['failed']} > {g['max_failures']}")
    if g.get("max_critical") is not None and summary["by_severity"].get("critical", 0) > g["max_critical"]:
        reasons.append(f"critical {summary['by_severity'].get('critical', 0)} > {g['max_critical']}")
    if g.get("max_high") is not None and summary["by_severity"].get("high", 0) > g["max_high"]:
        reasons.append(f"high {summary['by_severity'].get('high', 0)} > {g['max_high']}")
    return {"passed": not reasons, "reasons": reasons}


@router.post("/ci/scan", status_code=201)
def ci_scan(body: CiScanIn, user: User = Depends(api_token_user), session: Session = Depends(get_session)):
    if user.company_id is None:
        raise HTTPException(400, "CI token must belong to a company")
    if body.saved_target_id:
        st = session.get(SavedTarget, body.saved_target_id)
        if not st or (user.role != Role.global_admin and st.company_id != user.company_id):
            raise HTTPException(404, "No such saved target")
        import json
        target = Target(**json.loads(decrypt(st.config_enc)))
    elif body.target:
        target = body.target
    else:
        raise HTTPException(400, "Provide saved_target_id or target")

    tools = body.tools or {"promptfoo": True, "promptfoo_plugins": ["harmful", "pii"], "num_tests": 3}
    tools["gate"] = body.gate.model_dump()
    campaign = Campaign(company_id=user.company_id, name=body.name, created_by=user.id,
                        target=target.model_dump(), tools=tools)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    runner.start_campaign(campaign.id)
    return {"campaign_id": campaign.id, "status": "queued",
            "poll": f"/api/ci/scan/{campaign.id}"}


@router.get("/ci/scan/{campaign_id}")
def ci_scan_status(campaign_id: int, user: User = Depends(api_token_user),
                   session: Session = Depends(get_session)):
    c = session.get(Campaign, campaign_id)
    if not c or (user.role != Role.global_admin and c.company_id != user.company_id):
        raise HTTPException(404, "No such campaign")
    findings = [f.model_dump() for f in session.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()]
    summary = summarize(findings)
    done = c.status in ("completed", "stopped", "failed")
    gate = _gate_result(summary, (c.tools or {}).get("gate", {})) if done else {"passed": None, "reasons": []}
    return {"campaign_id": c.id, "status": c.status, "done": done,
            "summary": {k: summary[k] for k in ("risk_score", "risk_band", "total", "failed", "pass_rate", "by_severity")},
            "gate": gate}
