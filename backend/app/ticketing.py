"""Push findings to issue trackers (GitHub Issues / Jira). Configs are per-company
and encrypted at rest. Live creation needs the operator's token/project.
"""
import base64
import json
import logging
import threading
from typing import Any, Optional

import httpx
from sqlmodel import Session, select

from .crypto import decrypt
from .db import engine
from .models import Campaign, Finding, TicketConfig

log = logging.getLogger("xyberah.ticketing")
_TIMEOUT = 20
_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _title(f: Finding) -> str:
    return f"[{f.severity.upper()}] {f.plugin} — {f.category}"[:200]


def _body_md(f: Finding, c: Campaign) -> str:
    return (
        f"**Severity:** {f.severity}\n"
        f"**Tool:** {f.tool}  •  **Category:** {f.category}  •  **Plugin:** `{f.plugin}`\n"
        f"**Campaign:** {c.name} (#{c.id})\n\n"
        f"**Attack prompt:**\n```\n{(f.prompt or '')[:4000]}\n```\n"
        f"**Model response:**\n```\n{(f.output or '')[:4000]}\n```\n"
        f"**Why it failed:**\n{(f.reason or '')[:2000]}\n\n"
        f"_Filed by Xyberah AI red-teaming._"
    )


def create_ticket(kind: str, config: dict, f: Finding, c: Campaign) -> dict[str, Any]:
    try:
        if kind == "github":
            return _github(config, f, c)
        if kind == "jira":
            return _jira(config, f, c)
        return {"ok": False, "error": f"unknown tracker: {kind}"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"{e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _github(config: dict, f: Finding, c: Campaign) -> dict[str, Any]:
    repo = config.get("repo", "").strip("/")
    token = config.get("token", "")
    if not repo or not token:
        return {"ok": False, "error": "GitHub repo and token are required"}
    labels = [x for x in ["xyberah", f"severity:{f.severity}"] if x]
    payload = {"title": _title(f), "body": _body_md(f, c), "labels": labels}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(f"https://api.github.com/repos/{repo}/issues", json=payload,
                        headers={"Authorization": f"Bearer {token}",
                                 "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
    return {"ok": True, "url": data.get("html_url", ""), "key": f"#{data.get('number', '')}"}


def _jira(config: dict, f: Finding, c: Campaign) -> dict[str, Any]:
    base = config.get("base_url", "").rstrip("/")
    email = config.get("email", "")
    token = config.get("api_token", "")
    project = config.get("project_key", "")
    if not (base and email and token and project):
        return {"ok": False, "error": "Jira base_url, email, api_token and project_key are required"}
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    payload = {"fields": {
        "project": {"key": project},
        "summary": _title(f),
        "description": _body_md(f, c),
        "issuetype": {"name": config.get("issue_type", "Bug")},
        "labels": ["xyberah", f"severity-{f.severity}"],
    }}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(f"{base}/rest/api/2/issue", json=payload,
                        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
        r.raise_for_status()
        data = r.json()
    key = data.get("key", "")
    return {"ok": True, "url": f"{base}/browse/{key}" if key else "", "key": key}


def test_config(kind: str, config: dict) -> dict[str, Any]:
    """Validate credentials without creating an issue."""
    try:
        if kind == "github":
            repo = config.get("repo", "").strip("/")
            with httpx.Client(timeout=_TIMEOUT) as client:
                r = client.get(f"https://api.github.com/repos/{repo}",
                               headers={"Authorization": f"Bearer {config.get('token','')}",
                                        "Accept": "application/vnd.github+json"})
            return {"ok": r.status_code == 200, "error": "" if r.status_code == 200 else f"{r.status_code}: {r.text[:150]}"}
        if kind == "jira":
            base = config.get("base_url", "").rstrip("/")
            auth = base64.b64encode(f"{config.get('email','')}:{config.get('api_token','')}".encode()).decode()
            with httpx.Client(timeout=_TIMEOUT) as client:
                r = client.get(f"{base}/rest/api/2/myself", headers={"Authorization": f"Basic {auth}"})
            return {"ok": r.status_code == 200, "error": "" if r.status_code == 200 else f"{r.status_code}: {r.text[:150]}"}
        return {"ok": False, "error": "unknown tracker"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def auto_create(campaign_id: int, cap: int = 25) -> None:
    """On completion, file tickets for failing findings at/above the configured
    severity, for any company tracker with auto_create on. Runs in a thread."""
    def _run() -> None:
        try:
            with Session(engine) as s:
                c = s.get(Campaign, campaign_id)
                if not c:
                    return
                cfgs = s.exec(select(TicketConfig).where(
                    TicketConfig.enabled == True, TicketConfig.auto_create == True,  # noqa: E712
                    TicketConfig.company_id == c.company_id)).all()
                if not cfgs:
                    return
                for cfg in cfgs:
                    threshold = _SEV_RANK.get(cfg.min_severity, 1)
                    conf = json.loads(decrypt(cfg.config_enc) or "{}")
                    findings = s.exec(select(Finding).where(
                        Finding.campaign_id == campaign_id, Finding.passed == False)).all()  # noqa: E712
                    ranked = sorted(findings, key=lambda f: _SEV_RANK.get(f.severity, 9))
                    filed = 0
                    for f in ranked:
                        if filed >= cap:
                            break
                        if _SEV_RANK.get(f.severity, 9) > threshold or f.ticket_url:
                            continue
                        res = create_ticket(cfg.kind, conf, f, c)
                        if res.get("ok"):
                            f.ticket_url = res.get("url", "")
                            f.ticket_key = res.get("key", "")
                            s.add(f)
                            filed += 1
                        else:
                            log.warning("auto ticket failed (%s): %s", cfg.kind, res.get("error"))
                    s.commit()
        except Exception:
            log.exception("auto_create tickets failed for %s", campaign_id)

    threading.Thread(target=_run, name=f"tickets-{campaign_id}", daemon=True).start()
