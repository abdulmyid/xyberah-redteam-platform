"""Test a target's connectivity/auth/response before running a campaign.

The test runs server-side (like the real scan) so it validates the actual path:
reachability, HTTP method, headers/auth key, request body template, and whether
the configured response path extracts the model's reply.
"""
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from ..auth import company_scope, require_role
from ..db import get_session
from ..models import BrowserSession, Role, User
from ..orchestrator import browser_session
from ..orchestrator.targets import Target, missing_keys
from ..schemas import TargetTestIn

router = APIRouter(prefix="/api/targets", tags=["targets"])

MAX_SESSION = 2 * 1024 * 1024  # 2 MB storageState


@router.post("/browser-session", status_code=201)
def upload_browser_session(name: str = "", file: UploadFile = File(...),
                           user: User = Depends(require_role(Role.analyst)),
                           session: Session = Depends(get_session)):
    """Upload a Playwright storageState JSON (captured with `playwright codegen
    --save-storage`). Stored encrypted and reusable as a saved session."""
    raw = file.file.read(MAX_SESSION)
    try:
        import json as _json
        _json.loads(raw)
    except Exception:
        raise HTTPException(422, "Not valid JSON — upload the storageState file from `playwright codegen --save-storage`")
    row = browser_session.create_session(user.company_id, name or (file.filename or "session"),
                                          raw.decode("utf-8", "replace"), user.id)
    return {"id": row.id, "name": row.name, "created_at": row.created_at}


@router.get("/browser-sessions")
def list_browser_sessions(user: User = Depends(require_role(Role.analyst)),
                          session: Session = Depends(get_session)):
    scope = company_scope(user)
    q = select(BrowserSession).order_by(BrowserSession.created_at.desc())
    if scope is not None:
        q = q.where(BrowserSession.company_id == scope)
    return [{"id": r.id, "name": r.name, "created_at": r.created_at} for r in session.exec(q).all()]


@router.delete("/browser-sessions/{session_id}")
def delete_browser_session(session_id: int, user: User = Depends(require_role(Role.analyst)),
                           session: Session = Depends(get_session)):
    row = session.get(BrowserSession, session_id)
    if not row:
        raise HTTPException(404, "No such session")
    if user.role != Role.global_admin and row.company_id != user.company_id:
        raise HTTPException(404, "No such session")
    session.delete(row)
    session.commit()
    return {"ok": True}

DEFAULT_PROMPT = "Hello! Reply with a short confirmation that you are working."


def _fill(value: Any, prompt: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{prompt}}", prompt)
    if isinstance(value, dict):
        return {k: _fill(v, prompt) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, prompt) for v in value]
    return value


def _extract(data: Any, path: str) -> Any:
    cur = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, list) and part.lstrip("-").isdigit():
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(part)
    return cur


@router.post("/test")
def test_target(body: TargetTestIn, user: User = Depends(require_role(Role.analyst))):
    target = body.target
    prompt = body.prompt or DEFAULT_PROMPT

    # Browser (web chat UI) target: drive the Playwright bridge once.
    if target.type == "browser":
        return _test_browser(target, prompt, user.company_id)

    # Provider targets: we can only confirm the API key is present here.
    if target.type in ("openai", "anthropic"):
        missing = missing_keys(target)
        return {"ok": not missing, "kind": "provider",
                "message": ("API key is set — the scan will use it."
                            if not missing else f"Missing environment variable: {', '.join(missing)}")}
    if target.type == "ollama":
        return {"ok": True, "kind": "provider",
                "message": "Ollama target. Ensure the Ollama server is reachable from the backend."}

    h = target.http
    if not h:
        return {"ok": False, "kind": "http", "error": "No HTTP settings provided"}

    headers = {"Content-Type": "application/json", **h.headers}
    sent_body = _fill(h.body, prompt)
    result = _do_request(h.method, h.url, headers, sent_body)
    result["sent"] = {"method": h.method, "url": h.url, "body": sent_body}
    if result.get("json") is not None and result.get("ok"):
        try:
            reply = _extract(result["json"], h.response_path)
            result["reply"] = str(reply)[:1000]
        except Exception:
            result["ok"] = False
            result["extract_error"] = (
                f"Reached the endpoint, but could not read the reply at '{h.response_path}'. "
                f"Check the 'Response JSON path' against the raw response below.")
    result.pop("json", None)
    return result


def _test_browser(target: Target, prompt: str, company_id) -> dict:
    """Run the Playwright bridge once (node subprocess) to validate selectors."""
    import json
    import os
    import subprocess

    from ..config import get_settings

    b = target.browser
    bridge = get_settings().engine_dir / "providers" / "automated_chat_bridge.js"
    if not bridge.exists():
        return {"ok": False, "kind": "browser", "error": "browser bridge is not installed in this image"}

    with tempfile.TemporaryDirectory() as tmp:
        session_path = ""
        if b.session_id:
            session_path = browser_session.materialize(b.session_id, company_id, Path(tmp)) or ""
            if not session_path:
                return {"ok": False, "kind": "browser", "error": "saved session not found"}
        env = {
            **os.environ,  # keep PLAYWRIGHT_BROWSERS_PATH, NODE_PATH, PATH, etc.
            "CHAT_URL": b.url,
            "CHAT_INPUT_SELECTOR": b.input_selector,
            "CHAT_SEND_SELECTOR": b.send_button_selector,
            "CHAT_RESPONSE_SELECTOR": b.response_bubble_selector,
            "CHAT_STREAMING_SELECTOR": b.streaming_indicator_selector,
            "CHAT_NEWCHAT_SELECTOR": b.new_chat_selector,
            "CHAT_SETUP_STEPS": json.dumps([s.model_dump() for s in b.setup_steps]),
            "CHAT_STORAGE_STATE": session_path,
            "CHAT_HARD_TIMEOUT_MS": str(b.hard_timeout_ms),
            "CHAT_STABLE_MS": str(b.stable_ms),
            "CHAT_HEADLESS": "true",
        }
        try:
            proc = subprocess.run(["node", str(bridge), prompt], env=env, capture_output=True,
                                  text=True, timeout=b.hard_timeout_ms / 1000 + 25)
        except subprocess.TimeoutExpired:
            return {"ok": False, "kind": "browser", "error": "Timed out driving the chat UI."}
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out and not out.startswith("[BRIDGE ERROR]"):
        return {"ok": True, "kind": "browser", "reply": out[:1000]}
    return {"ok": False, "kind": "browser",
            "error": out or (proc.stderr or "").strip()[-400:] or "bridge failed",
            "raw": (proc.stderr or "")[-1500:]}


def _do_request(method: str, url: str, headers: dict, body: Any) -> dict:
    def call(verify: bool) -> httpx.Response:
        with httpx.Client(timeout=20, verify=verify, follow_redirects=True) as client:
            if method.upper() == "GET":
                return client.get(url, headers=headers, params=body if isinstance(body, dict) else None)
            return client.post(url, headers=headers, json=body)

    tls_note = None
    try:
        try:
            r = call(verify=True)
        except httpx.ConnectError as exc:
            if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
                r = call(verify=False)
                tls_note = "Warning: the TLS certificate is not trusted (test ran without verification)."
            else:
                raise
    except httpx.TimeoutException:
        return {"ok": False, "kind": "http", "error": "Timed out after 20s — endpoint unreachable or slow."}
    except Exception as exc:
        return {"ok": False, "kind": "http", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    out: dict[str, Any] = {"kind": "http", "status": r.status_code,
                           "ok": 200 <= r.status_code < 300, "raw": r.text[:2000]}
    if tls_note:
        out["tls_note"] = tls_note
    if not out["ok"]:
        out["error"] = f"Endpoint returned HTTP {r.status_code} (check the URL, method, or auth key)."
    try:
        out["json"] = r.json()
    except Exception:
        out["json"] = None
        if out["ok"]:
            out["ok"] = False
            out["error"] = "Endpoint replied, but the body was not JSON."
    return out
