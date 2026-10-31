"""Recurring campaigns. A single background thread wakes every minute, starts any
schedule that is due, and computes its next run. Times are UTC."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from .db import engine
from .models import Campaign, PromptSet, Schedule, utcnow

log = logging.getLogger("xyberah.scheduler")
_TICK_SECONDS = 60
_started = False
_last_retention = 0.0
_RETENTION_EVERY = 3600  # run the retention sweep at most hourly


def next_run(freq: dict[str, Any], after: Optional[datetime] = None) -> datetime:
    now = after or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    kind = (freq or {}).get("kind", "daily")
    if kind == "interval":
        minutes = max(int(freq.get("minutes", 1440)), 5)
        return now + timedelta(minutes=minutes)

    at = str(freq.get("at", "02:00"))
    try:
        hh, mm = (int(x) for x in at.split(":", 1))
    except Exception:
        hh, mm = 2, 0
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if kind == "weekly":
        target_day = int(freq.get("day", 0)) % 7  # 0 = Monday
        delta = (target_day - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=delta)
        if candidate <= now:
            candidate = candidate + timedelta(days=7)
    else:  # daily
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
    return candidate


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="xyberah-scheduler", daemon=True)
    t.start()
    log.info("scheduler started")


def _loop() -> None:
    while True:
        try:
            _tick()
            _maybe_retention()
        except Exception:
            log.exception("scheduler tick failed")
        time.sleep(_TICK_SECONDS)


def _maybe_retention() -> None:
    global _last_retention
    if time.time() - _last_retention < _RETENTION_EVERY:
        return
    _last_retention = time.time()
    from .governance import retention_sweep
    with Session(engine) as s:
        retention_sweep(s)


def _tick() -> None:
    from .orchestrator import runner

    now = datetime.now(timezone.utc)
    launched: list[int] = []
    with Session(engine) as s:
        due: list[Schedule] = []
        for sch in s.exec(select(Schedule).where(Schedule.enabled == True)).all():  # noqa: E712
            if sch.next_run_at is None:
                sch.next_run_at = next_run(sch.freq, now)
                s.add(sch)
                continue
            nr = sch.next_run_at
            if nr.tzinfo is None:
                nr = nr.replace(tzinfo=timezone.utc)
            if nr <= now:
                due.append(sch)
        s.commit()

        for sch in due:
            try:
                cid = _launch(s, sch, now)
                sch.last_run_at = now
                sch.last_campaign_id = cid
                launched.append(cid)
            except Exception:
                log.exception("failed to launch schedule %s", sch.id)
            sch.next_run_at = next_run(sch.freq, now)
            s.add(sch)
        s.commit()

    # Start campaigns outside the session so the runner opens its own.
    for cid in launched:
        runner.start_campaign(cid)


def _launch(s: Session, sch: Schedule, now: datetime) -> int:
    """Create a Campaign from the schedule template (status=queued) and return its id."""
    tpl = sch.template or {}
    tools = dict(tpl.get("tools") or {})
    # Snapshot a referenced prompt set, same as the create-campaign route.
    if tools.get("custom") and tools.get("prompt_set_id") and not tools.get("custom_prompts"):
        ps = s.get(PromptSet, tools["prompt_set_id"])
        if ps and (ps.company_id == sch.company_id or ps.company_id is None):
            tools["custom_prompts"] = ps.prompts or []
            tools["custom_grading"] = ps.grading or {}
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    campaign = Campaign(
        company_id=sch.company_id,
        name=f"{tpl.get('name') or sch.name} [scheduled {stamp}]",
        description=f"Automated run of schedule: {sch.name}",
        created_by=sch.created_by,
        target=tpl.get("target") or {},
        tools=tools,
        status="queued",
    )
    s.add(campaign)
    s.commit()
    s.refresh(campaign)
    return campaign.id


def run_now(schedule_id: int) -> Optional[int]:
    """Launch a schedule immediately (used by the 'run now' action)."""
    from .orchestrator import runner

    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        sch = s.get(Schedule, schedule_id)
        if not sch:
            return None
        cid = _launch(s, sch, now)
        sch.last_run_at = now
        sch.last_campaign_id = cid
        s.add(sch)
        s.commit()
    runner.start_campaign(cid)
    return cid
