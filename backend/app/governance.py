"""Data-governance helpers: per-company usage/budget accounting and retention."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from .db import engine
from .models import Campaign, Company, Finding

log = logging.getLogger("xyberah.governance")


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_usage(session: Session, company_id: int) -> dict[str, Any]:
    """Cost / tokens / campaign count for the current calendar month (UTC),
    summed from the findings of campaigns finished this month."""
    start = _month_start(datetime.now(timezone.utc))
    camps = session.exec(select(Campaign).where(Campaign.company_id == company_id)).all()
    cost = 0.0
    tokens = 0
    n = 0
    for c in camps:
        fin = c.finished_at
        if not fin:
            continue
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        if fin < start:
            continue
        n += 1
        for f in session.exec(select(Finding).where(Finding.campaign_id == c.id)).all():
            extra = f.extra or {}
            cost += float(extra.get("cost") or 0)
            tokens += int(extra.get("tokens") or 0)
    return {"cost": round(cost, 4), "tokens": tokens, "campaigns": n,
            "month": start.strftime("%Y-%m")}


def budget_status(session: Session, company: Company) -> dict[str, Any]:
    usage = month_usage(session, company.id)
    over_cost = bool(company.monthly_cost_budget and usage["cost"] >= company.monthly_cost_budget)
    over_tokens = bool(company.monthly_token_budget and usage["tokens"] >= company.monthly_token_budget)
    return {
        **usage,
        "cost_budget": company.monthly_cost_budget,
        "token_budget": company.monthly_token_budget,
        "over_budget": over_cost or over_tokens,
        "over_cost": over_cost, "over_tokens": over_tokens,
        "enforce": company.budget_enforce,
    }


def retention_sweep(session: Session) -> int:
    """Delete campaigns (and their findings) older than each company's retention
    window. Returns the number of campaigns removed. 0 retention_days = keep."""
    now = datetime.now(timezone.utc)
    removed = 0
    companies = {c.id: c for c in session.exec(select(Company)).all()}
    for c in session.exec(select(Campaign)).all():
        company = companies.get(c.company_id)
        if not company or not company.retention_days:
            continue
        ref = c.finished_at or c.created_at
        if not ref:
            continue
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        if c.status in ("running", "queued", "paused"):
            continue
        if ref < now - timedelta(days=company.retention_days):
            for f in session.exec(select(Finding).where(Finding.campaign_id == c.id)).all():
                session.delete(f)
            session.delete(c)
            removed += 1
    if removed:
        session.commit()
        log.info("retention sweep removed %d campaigns", removed)
    return removed
