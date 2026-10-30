"""Model Audit: scan an uploaded model file for malicious code / unsafe content
using the `modelaudit` scanner (pickle exploits, unsafe deserialization, etc.)."""
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth import require_role
from ..config import get_settings
from ..models import Role, User

router = APIRouter(prefix="/api/modelaudit", tags=["modelaudit"])

MAX_UPLOAD = 300 * 1024 * 1024  # 300 MB
# modelaudit severity -> our scale
SEV_MAP = {"critical": "critical", "error": "critical", "warning": "high",
           "info": "medium", "debug": "low", "notice": "medium"}


@router.get("/status")
def status(user: User = Depends(require_role(Role.analyst))):
    py = get_settings().modelaudit_python
    return {"available": py.exists()}


@router.post("/scan")
def scan(file: UploadFile = File(...), user: User = Depends(require_role(Role.analyst))):
    settings = get_settings()
    py = settings.modelaudit_python
    if not py.exists():
        raise HTTPException(503, "ModelAudit is not installed in this image")

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / (Path(file.filename or "model.bin").name or "model.bin")
        size = 0
        with dest.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "File too large (max 300 MB)")
                out.write(chunk)

        try:
            proc = subprocess.run([str(py), "-m", "modelaudit", "scan", str(dest), "--format", "json"],
                                  capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Scan timed out")

        data = _parse(proc.stdout)
        if data is None:
            return {"ok": False, "filename": file.filename, "size": size,
                    "error": (proc.stderr or proc.stdout or "scan produced no JSON")[-800:]}
        issues = _issues(data)
        by_sev: dict[str, int] = {}
        for i in issues:
            by_sev[i["severity"]] = by_sev.get(i["severity"], 0) + 1
        return {"ok": True, "filename": file.filename, "size": size,
                "total_issues": len(issues), "by_severity": by_sev, "issues": issues[:500]}


def _parse(stdout: str) -> Any:
    stdout = (stdout or "").strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        # tolerate leading log lines: take from the first '{'
        start = stdout.find("{")
        if start >= 0:
            try:
                return json.loads(stdout[start:])
            except json.JSONDecodeError:
                return None
    return None


def _issues(data: Any) -> list[dict]:
    raw = []
    if isinstance(data, dict):
        raw = data.get("issues") or data.get("results") or []
        if not raw and isinstance(data.get("assets"), list):
            for a in data["assets"]:
                raw.extend(a.get("issues") or [])
    out = []
    for i in raw:
        if not isinstance(i, dict):
            continue
        sev = str(i.get("severity", "info")).lower()
        why = i.get("why") or ""
        if not why and i.get("details") is not None:
            d = i["details"]
            why = json.dumps(d) if isinstance(d, (dict, list)) else str(d)
        out.append({
            "severity": SEV_MAP.get(sev, "medium"),
            "raw_severity": sev,
            "message": str(i.get("message") or i.get("title") or i.get("check") or "issue"),
            "location": str(i.get("location") or i.get("path") or i.get("file") or ""),
            "rule_code": str(i.get("rule_code") or i.get("type") or ""),
            "why": str(why)[:500],
        })
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda x: order.get(x["severity"], 9))
    return out
