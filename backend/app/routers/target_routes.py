"""Test a target's connectivity/auth/response before running a campaign.

The test runs server-side (like the real scan) so it validates the actual path:
reachability, HTTP method, headers/auth key, request body template, and whether
the configured response path extracts the model's reply.
"""
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from ..auth import require_role
from ..models import Role, User
from ..orchestrator.targets import Target, missing_keys
from ..schemas import TargetTestIn

router = APIRouter(prefix="/api/targets", tags=["targets"])

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
