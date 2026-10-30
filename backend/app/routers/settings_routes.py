"""Branding (per-company), logo uploads, scan catalog, and tool versions/updates."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..auth import current_user, global_admin, require_role
from ..branding import (default_branding, load_branding, save_company_branding, save_default)
from ..config import get_settings
from ..models import Role, User
from ..orchestrator import catalog, garak_runner
from ..orchestrator.inspect_runner import INSPECT_TASKS
from ..orchestrator.pyrit_attacks import DEFAULT_OBJECTIVES, PYRIT_ATTACKS
from ..orchestrator.tools import list_tool_versions, update_tool
from ..schemas import BrandingIn

router = APIRouter(prefix="/api", tags=["settings"])
ALLOWED_LOGO = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


@router.get("/branding")
def get_branding():
    """Public: themes the login page before sign-in (instance default)."""
    return default_branding().model_dump()


@router.get("/branding/me")
def my_branding(user: User = Depends(current_user)):
    return load_branding(user.company_id).model_dump()


@router.put("/branding")
def put_branding(body: BrandingIn, user: User = Depends(require_role(Role.company_admin))):
    values = body.model_dump(exclude_none=True)
    if user.role == Role.global_admin and user.company_id is None:
        return save_default(values).model_dump()
    return save_company_branding(user.company_id, values).model_dump()


@router.post("/branding/logo")
def upload_logo(slot: str, file: UploadFile = File(...),
                user: User = Depends(require_role(Role.company_admin))):
    if slot not in {"logo_light", "logo_dark", "favicon"}:
        raise HTTPException(400, "slot must be logo_light, logo_dark or favicon")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_LOGO:
        raise HTTPException(400, f"Unsupported file type {ext}")
    scope = user.company_id if user.company_id is not None else 0
    dest_dir = get_settings().uploads_dir / str(scope)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{slot}.*"):
        old.unlink()
    dest = dest_dir / f"{slot}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    url = f"/uploads/{scope}/{dest.name}"
    if user.company_id is None:
        save_default({slot: url})
    else:
        save_company_branding(user.company_id, {slot: url})
    return {"url": url}


@router.get("/catalog")
def get_catalog(user: User = Depends(current_user)):
    return {
        "promptfoo": {"plugins": catalog.PROMPTFOO_PLUGINS, "strategies": catalog.PROMPTFOO_STRATEGIES, "presets": catalog.PROMPTFOO_PRESETS},
        "garak": {"probes": garak_runner.GARAK_PROBES},
        "pyrit": {"attacks": PYRIT_ATTACKS, "default_objectives": DEFAULT_OBJECTIVES},
        "inspect": {"tasks": INSPECT_TASKS},
        "categories": catalog.CATEGORIES,
    }


@router.get("/tools/versions")
def tool_versions(user: User = Depends(current_user)):
    return list_tool_versions()


@router.post("/tools/{tool}/update")
def tools_update(tool: str, admin: User = Depends(global_admin)):
    if tool not in {"garak", "pyrit", "inspect"}:
        raise HTTPException(404, "Unknown tool")
    return update_tool(tool)
