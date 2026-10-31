"""Operational health metrics and cleanup utilities (global-admin)."""
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from .config import get_settings
from .db import engine
from .models import AuditLog, Campaign, Company, Finding, PromptSet, Schedule, User


def _dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for root, _dirs, files in os.walk(p):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _count(s: Session, model) -> int:
    return s.exec(select(func.count()).select_from(model)).one()


def health() -> dict[str, Any]:
    st = get_settings()
    db_path = st.data_dir / "xyberah.db"
    db_size = db_path.stat().st_size if db_path.exists() else 0
    outbox = st.data_dir / "outbox"
    try:
        du = shutil.disk_usage(str(st.data_dir))
        disk = {"total": du.total, "used": du.used, "free": du.free,
                "percent_used": round(100 * du.used / du.total, 1) if du.total else 0}
    except OSError:
        disk = {}

    with Session(engine) as s:
        by_status: dict[str, int] = {}
        for c in s.exec(select(Campaign)).all():
            by_status[c.status] = by_status.get(c.status, 0) + 1
        counts = {
            "companies": _count(s, Company), "users": _count(s, User),
            "campaigns": _count(s, Campaign), "findings": _count(s, Finding),
            "audit_rows": _count(s, AuditLog), "prompt_sets": _count(s, PromptSet),
            "schedules": _count(s, Schedule),
        }

    from .orchestrator.tools import list_tool_versions
    try:
        tools = {k: {"installed": v.get("installed"), "ready": v.get("ready")}
                 for k, v in list_tool_versions().items()}
    except Exception:
        tools = {}

    from .audit import get_syslog
    from .email_service import get_smtp
    return {
        "storage": {
            "db_bytes": db_size,
            "campaigns_bytes": _dir_size(st.campaigns_dir),
            "uploads_bytes": _dir_size(st.uploads_dir),
            "outbox_bytes": _dir_size(outbox),
            "data_bytes": _dir_size(st.data_dir),
        },
        "disk": disk,
        "counts": counts,
        "campaign_status": by_status,
        "running": by_status.get("running", 0) + by_status.get("queued", 0),
        "tools": tools,
        "smtp_configured": get_smtp().get("configured", False),
        "syslog_enabled": get_syslog().get("enabled", False),
    }


def cleanup(events_days: int = 0, clear_outbox: bool = False, vacuum: bool = False) -> dict[str, Any]:
    """Prune old live-event logs, optionally clear the dev outbox and VACUUM the DB."""
    import time
    st = get_settings()
    result: dict[str, Any] = {"events_removed": 0, "outbox_removed": 0, "vacuumed": False}

    if events_days and events_days > 0:
        cutoff = time.time() - events_days * 86400
        for camp_dir in st.campaigns_dir.glob("*"):
            ev = camp_dir / "events.jsonl"
            try:
                if ev.exists() and ev.stat().st_mtime < cutoff:
                    ev.unlink()
                    result["events_removed"] += 1
            except OSError:
                pass

    if clear_outbox:
        outbox = st.data_dir / "outbox"
        if outbox.exists():
            for f in outbox.glob("*.eml"):
                try:
                    f.unlink()
                    result["outbox_removed"] += 1
                except OSError:
                    pass

    if vacuum:
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("VACUUM")
            result["vacuumed"] = True
        except Exception:
            result["vacuumed"] = False

    return result
