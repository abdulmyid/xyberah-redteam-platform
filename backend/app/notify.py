"""Outbound alerts to Slack / Microsoft Teams / generic webhooks, fired when a
campaign finishes. Best-effort: failures are logged, never raised to the caller."""
import json
import logging
import threading
import urllib.request
from typing import Any

from sqlmodel import Session, select

from .crypto import decrypt
from .db import engine
from .models import Campaign, Finding, NotifyChannel
from .reports.aggregate import summarize

log = logging.getLogger("xyberah.notify")
_TIMEOUT = 10


def _post(url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (user-configured URL)
        r.read()


def _slack_text(summary: dict, c: Campaign, base: str) -> str:
    sev = summary.get("by_severity", {})
    line = (f"*{c.name}* finished — risk *{summary.get('risk_score', 0)}* "
            f"({summary.get('risk_band', 'low')}). "
            f"{summary.get('failed', 0)}/{summary.get('total', 0)} failed · "
            f"{sev.get('critical', 0)} critical, {sev.get('high', 0)} high.")
    if base:
        line += f"\n{base}/campaigns/{c.id}"
    return line


def _payload(kind: str, summary: dict, c: Campaign, base: str) -> dict[str, Any]:
    if kind == "slack":
        return {"text": _slack_text(summary, c, base)}
    if kind == "teams":
        return {"text": _slack_text(summary, c, base).replace("*", "**")}
    # generic webhook: structured JSON
    return {
        "event": "campaign.completed",
        "campaign": {"id": c.id, "name": c.name, "status": c.status,
                     "target": (c.target or {}).get("type"),
                     "finished_at": c.finished_at.isoformat() if c.finished_at else None},
        "summary": {k: summary.get(k) for k in
                    ("risk_score", "risk_band", "total", "failed", "pass_rate", "by_severity")},
        "url": f"{base}/campaigns/{c.id}" if base else None,
    }


def notify_campaign(campaign_id: int, base_url: str = "") -> None:
    """Fire configured alerts for a finished campaign (runs in a daemon thread)."""
    def _run() -> None:
        try:
            with Session(engine) as s:
                c = s.get(Campaign, campaign_id)
                if not c:
                    return
                findings = s.exec(select(Finding).where(Finding.campaign_id == campaign_id)).all()
                summary = summarize([f.model_dump() for f in findings])
                channels = s.exec(select(NotifyChannel).where(
                    NotifyChannel.enabled == True,  # noqa: E712
                    NotifyChannel.company_id == c.company_id)).all()
                base = base_url
                if not base:
                    from .models import Setting
                    row = s.get(Setting, "public_base_url")
                    base = (row.value if row and isinstance(row.value, str) else "") or ""
                base = base.rstrip("/")
                from .models import Company
                from .governance import budget_status
                company = s.get(Company, c.company_id)
                budget = budget_status(s, company) if company else {"over_budget": False}
            risk = summary.get("risk_score", 0)
            for ch in channels:
                if not ch.on_complete or risk < (ch.min_risk or 0):
                    continue
                url = decrypt(ch.url_enc)
                if not url:
                    continue
                try:
                    payload = _payload(ch.kind, summary, c, base)
                    if budget.get("over_budget"):
                        if ch.kind in ("slack", "teams"):
                            payload["text"] += "\n:warning: Monthly budget exceeded for this company."
                        else:
                            payload["budget_exceeded"] = True
                    _post(url, payload)
                except Exception as exc:
                    log.warning("notify channel %s failed: %s", ch.id, exc)
        except Exception:
            log.exception("notify_campaign failed")

    threading.Thread(target=_run, name=f"notify-{campaign_id}", daemon=True).start()


def send_test(kind: str, url: str) -> dict[str, Any]:
    """Send a one-off test message to verify a channel."""
    text = "Xyberah test alert — your channel is configured correctly."
    payload = {"text": text} if kind in ("slack", "teams") else {"event": "test", "message": text}
    try:
        _post(url, payload)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


# ---- SIEM export (ArcSight CEF) -------------------------------------------- #
_CEF_SEV = {"critical": 10, "high": 8, "medium": 5, "low": 2}


def _cef_escape(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _cef_ext(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace("=", "\\=").replace("\n", " ")


def findings_to_cef(campaign: Campaign, findings: list[Finding]) -> str:
    """One CEF line per failed finding, for syslog/Splunk/ArcSight ingestion."""
    lines = []
    for f in findings:
        if f.passed:
            continue
        name = _cef_escape(f.plugin or f.category or "finding")
        sev = _CEF_SEV.get(f.severity, 3)
        ext = " ".join([
            f"cat={_cef_ext(f.category)}",
            f"cs1Label=Tool cs1={_cef_ext(f.tool)}",
            f"cs2Label=Status cs2={_cef_ext(f.status or 'open')}",
            f"cs3Label=Campaign cs3={_cef_ext(campaign.name)}",
            f"externalId={f.id}",
            f"msg={_cef_ext((f.reason or f.prompt or '')[:400])}",
        ])
        lines.append(f"CEF:0|Xyberah|RedTeam|1.0|{name}|{name}|{sev}|{ext}")
    return "\n".join(lines) + ("\n" if lines else "")
