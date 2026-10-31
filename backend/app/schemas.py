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


# ---- prompt sets / datasets ------------------------------------------------ #
class Grading(BaseModel):
    use_rubric: bool = True
    rubric: str = ""
    must_not_contain: list[str] = Field(default_factory=list)
    must_contain: list[str] = Field(default_factory=list)
    severity: str = "high"


class PromptSetIn(BaseModel):
    name: str
    description: str = ""
    prompts: list[str] = Field(default_factory=list)
    grading: Grading = Field(default_factory=Grading)


# ---- campaigns ------------------------------------------------------------- #
class ToolSelection(BaseModel):
    promptfoo: bool = True
    garak: bool = False
    pyrit: bool = False
    inspect: bool = False
    custom: bool = False
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
    indirect_var: str = ""  # RAG: the prompt var that carries untrusted retrieved content
    # Custom prompts (own dataset). prompt_set_id references a saved library set;
    # it is resolved into custom_prompts/custom_grading at campaign creation so the
    # run is reproducible even if the library set is later edited.
    prompt_set_id: Optional[int] = None
    custom_prompts: list[str] = Field(default_factory=list)
    custom_grading: dict = Field(default_factory=dict)


class TargetTestIn(BaseModel):
    target: Target
    prompt: str = ""


class SavedTargetIn(BaseModel):
    name: str = ""
    target: Target


class CampaignIn(BaseModel):
    name: str
    description: str = ""
    target: Target
    tools: ToolSelection


# ---- finding triage / remediation ----------------------------------------- #
class FindingUpdateIn(BaseModel):
    status: Optional[str] = None  # open | triaged | fixed | accepted_risk | false_positive
    assignee_id: Optional[int] = None
    triage_note: Optional[str] = None


class BulkFindingIn(BaseModel):
    ids: list[int] = Field(default_factory=list)
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    triage_note: Optional[str] = None


# ---- schedules ------------------------------------------------------------- #
class Freq(BaseModel):
    kind: str = "daily"           # interval | daily | weekly
    minutes: int = 1440           # for kind=interval
    at: str = "02:00"             # for kind=daily/weekly, UTC HH:MM
    day: int = 0                  # for kind=weekly, 0=Monday


class ScheduleIn(BaseModel):
    name: str
    template: CampaignIn
    freq: Freq = Field(default_factory=Freq)
    enabled: bool = True


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
