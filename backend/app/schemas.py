from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

from .models import Role
from .orchestrator.targets import Target


# ---- auth / mfa ------------------------------------------------------------ #
class SetupIn(BaseModel):
    email: str
    username: str = ""
    password: str


class LoginIn(BaseModel):
    email: str  # not EmailStr: internal domains (e.g. admin@xyberah.local) must log in
    password: str


class MfaVerifyIn(BaseModel):
    mfa_token: str
    method: str  # "totp" | "email"
    code: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class TotpEnableIn(BaseModel):
    secret: str
    code: str


# ---- companies / users / invites ------------------------------------------ #
class CompanyIn(BaseModel):
    name: str
    slug: Optional[str] = None
    max_users: int = 25
    max_concurrent_campaigns: int = 1


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.viewer
    company_id: Optional[int] = None  # global admin may target any company


class AcceptInviteIn(BaseModel):
    token: str
    username: str
    password: str


class RoleUpdateIn(BaseModel):
    role: Role


# ---- SMTP ------------------------------------------------------------------ #
class SmtpIn(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    from_addr: Optional[str] = None
    from_name: Optional[str] = None
    use_tls: Optional[bool] = None


# ---- campaigns ------------------------------------------------------------- #
class ToolSelection(BaseModel):
    promptfoo: bool = True
    garak: bool = False
    pyrit: bool = False
    inspect: bool = False
    purpose: str = ""
    promptfoo_plugins: list[str] = Field(default_factory=list)
    promptfoo_strategies: list[str] = Field(default_factory=lambda: ["basic"])
    garak_probes: list[str] = Field(default_factory=list)
    pyrit_attacks: list[str] = Field(default_factory=list)
    pyrit_objectives: list[str] = Field(default_factory=list)
    pyrit_max_turns: int = 5
    inspect_tasks: list[str] = Field(default_factory=list)
    num_tests: int = 5
    garak_generations: int = 5


class CampaignIn(BaseModel):
    name: str
    description: str = ""
    target: Target
    tools: ToolSelection


class BrandingIn(BaseModel):
    app_name: Optional[str] = None
    tagline: Optional[str] = None
    primary: Optional[str] = None
    secondary: Optional[str] = None
    accent: Optional[str] = None
    hide_footer: Optional[bool] = None
    footer_text: Optional[str] = None
    support_url: Optional[str] = None
    logo_light: Optional[str] = None
    logo_dark: Optional[str] = None
    favicon: Optional[str] = None
