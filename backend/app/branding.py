"""Per-company white-label branding.

Each company has a CompanyBranding row. Unset fields fall back to the instance
default, which a global admin edits (persisted in the branding YAML file so it
can also be baked into an image). Company admins edit their own company's theme.
"""
import re
from typing import Any, Optional

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session

from .config import get_settings
from .db import engine
from .models import CompanyBranding

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class Branding(BaseModel):
    app_name: str = "Xyberah"
    tagline: str = "AI Red-Teaming & Security Evaluation"
    logo_light: str = "/static/branding/logo-light.svg"
    logo_dark: str = "/static/branding/logo-dark.svg"
    favicon: str = "/static/branding/favicon.svg"
    primary: str = "#6d28d9"
    secondary: str = "#0ea5e9"
    accent: str = "#f43f5e"
    hide_footer: bool = False
    footer_text: str = "Built by xyberah.com · Powered by Promptfoo, garak, PyRIT and Inspect AI"
    support_url: str = ""

    @field_validator("primary", "secondary", "accent")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError("colors must be hex like #6d28d9")
        return v.lower()


def default_branding() -> Branding:
    path = get_settings().branding_file
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return Branding(**data)
        except Exception:
            pass
    return Branding()


def save_default(values: dict[str, Any]) -> Branding:
    if get_settings().branding_locked:
        raise HTTPException(403, "Branding is locked by the administrator")
    merged = {**default_branding().model_dump(), **{k: v for k, v in values.items() if v is not None}}
    branding = Branding(**merged)
    path = get_settings().branding_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(branding.model_dump(), sort_keys=False), encoding="utf-8")
    return branding


def load_branding(company_id: Optional[int]) -> Branding:
    base = default_branding().model_dump()
    if company_id is not None:
        with Session(engine) as s:
            row = s.get(CompanyBranding, company_id)
        if row and row.data:
            base.update({k: v for k, v in row.data.items() if v is not None})
    try:
        return Branding(**base)
    except Exception:
        return default_branding()


def save_company_branding(company_id: int, values: dict[str, Any]) -> Branding:
    if get_settings().branding_locked:
        raise HTTPException(403, "Branding is locked by the administrator")
    with Session(engine) as s:
        row = s.get(CompanyBranding, company_id)
        data = dict(row.data) if row and row.data else {}
        data.update({k: v for k, v in values.items() if v is not None})
        Branding(**{**default_branding().model_dump(), **data})  # validate
        if row:
            row.data = data
        else:
            row = CompanyBranding(company_id=company_id, data=data)
        s.add(row)
        s.commit()
    return load_branding(company_id)
