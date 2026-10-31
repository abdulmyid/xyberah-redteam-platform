"""Multi-tenant data model.

Tenancy: every row a company owns carries `company_id`. Global admins have
company_id = None and may act across companies; everyone else is confined to
their own company (enforced in auth.scoped_* helpers and the routers).

Roles (most to least privileged):
  global_admin   - manages companies and all users; instance-wide SMTP
  company_admin  - manages their company's users, branding, invites
  analyst        - creates, runs and reports on campaigns in their company
  viewer         - read-only access to their company's campaigns and reports
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    global_admin = "global_admin"
    company_admin = "company_admin"
    analyst = "analyst"
    viewer = "viewer"


# Rank for "at least this role" checks within a company
ROLE_RANK = {Role.viewer: 0, Role.analyst: 1, Role.company_admin: 2, Role.global_admin: 3}


class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    slug: str = Field(index=True, unique=True)
    disabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    # Per-company resource guard rails
    max_users: int = 25
    max_concurrent_campaigns: int = 1
    # Data governance
    redact_findings: bool = False        # scrub PII/secrets from stored finding text
    retention_days: int = 0              # auto-delete campaigns older than N days (0 = keep)
    monthly_cost_budget: float = 0.0     # USD; 0 = no budget
    monthly_token_budget: int = 0        # tokens; 0 = no budget
    budget_enforce: bool = False         # block new campaigns when a budget is exceeded


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    username: str = Field(index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    role: Role = Field(default=Role.viewer)
    password_hash: str = ""
    disabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_login: Optional[datetime] = None
    # 2FA (optional, per-user)
    totp_secret_enc: str = ""          # Fernet-encrypted base32 seed
    totp_enabled: bool = False
    email_otp_enabled: bool = False
    # SSO / provisioning
    auth_provider: str = "local"       # local | oidc | saml | scim
    external_id: str = ""              # IdP subject / SCIM externalId


class Invite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True)
    email: str = Field(index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id")
    role: Role = Role.viewer
    invited_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    accepted_at: Optional[datetime] = None


class LoginCode(SQLModel, table=True):
    """Short-lived hashed codes for email-OTP login and (reused) MFA challenges."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    code_hash: str
    purpose: str = "login"  # login | email_verify
    expires_at: datetime
    consumed: bool = False
    attempts: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    name: str
    description: str = ""
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    status: str = "draft"
    target: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    tools: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    stages: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    pause_requested: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: str = ""


class Finding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    tool: str
    category: str
    plugin: str
    severity: str
    passed: bool
    score: Optional[float] = None
    prompt: str = Field(default="", sa_column=Column(Text))
    output: str = Field(default="", sa_column=Column(Text))
    reason: str = Field(default="", sa_column=Column(Text))
    extra: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # Triage / remediation lifecycle
    status: str = "open"  # open | triaged | fixed | accepted_risk | false_positive
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
    triage_note: str = Field(default="", sa_column=Column(Text))
    retest_output: str = Field(default="", sa_column=Column(Text))
    retest_passed: Optional[bool] = None
    retested_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = Field(default=None, foreign_key="user.id")
    # Issue-tracker linkage
    ticket_url: str = ""
    ticket_key: str = ""


class CompanyBranding(SQLModel, table=True):
    company_id: int = Field(primary_key=True, foreign_key="company.id")
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ShareLink(SQLModel, table=True):
    token: str = Field(primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None
    revoked: bool = False


class Setting(SQLModel, table=True):
    """Instance-wide settings (e.g. SMTP), managed by global admins."""

    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(JSON))


class AuditLog(SQLModel, table=True):
    """Append-only record of every state-changing API call, hash-chained so any
    deletion or edit of history is detectable (each row's hash covers the prior
    row's hash)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    user_id: Optional[int] = Field(default=None, index=True)
    user_email: str = ""
    company_id: Optional[int] = Field(default=None, index=True)
    method: str = ""
    path: str = ""
    status: int = 0
    ip: str = ""
    prev_hash: str = ""
    row_hash: str = Field(default="", index=True)


class BrowserSession(SQLModel, table=True):
    """A saved, authenticated browser session (Playwright storageState) for a web
    chat UI target. The session JSON (cookies/localStorage) is encrypted at rest."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    name: str = ""
    data_enc: str = Field(default="", sa_column=Column(Text))  # Fernet-encrypted storageState JSON
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class SavedTarget(SQLModel, table=True):
    """A reusable target configuration (e.g. a configured Gemini/HTTP endpoint or a
    browser chat UI). The config may hold API keys in headers, so it is encrypted
    at rest and scoped to the company."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    name: str = ""
    target_type: str = ""  # openai | anthropic | ollama | http | browser
    config_enc: str = Field(default="", sa_column=Column(Text))  # Fernet-encrypted Target JSON
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class ApiToken(SQLModel, table=True):
    """A bearer token for CI/CD and automation. Only the hash is stored; the
    plaintext is shown once at creation. Acts as the creating user (tenancy/role)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True)
    name: str = ""
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    last_used: Optional[datetime] = None
    revoked: bool = False


class SsoConfig(SQLModel, table=True):
    """Instance-wide SSO configuration (single row, id=1). Secrets encrypted at rest."""

    id: Optional[int] = Field(default=1, primary_key=True)
    oidc_enabled: bool = False
    oidc_issuer: str = ""                    # base issuer URL (OIDC discovery)
    oidc_client_id: str = ""
    oidc_client_secret_enc: str = ""
    oidc_scopes: str = "openid email profile"
    saml_enabled: bool = False
    saml_idp_entity_id: str = ""
    saml_idp_sso_url: str = ""
    saml_idp_x509: str = Field(default="", sa_column=Column(Text))  # IdP signing cert (PEM/base64)
    sp_base_url: str = ""                     # public base URL of this app (for ACS/redirect)
    default_role: str = "viewer"
    auto_provision: bool = True              # JIT-create users on first SSO login


class SsoDomainMap(SQLModel, table=True):
    """Maps an email domain to a company (and default role) for JIT provisioning."""

    id: Optional[int] = Field(default=None, primary_key=True)
    domain: str = Field(index=True)          # lowercase, e.g. "acme.com"
    company_id: int = Field(foreign_key="company.id", index=True)
    default_role: str = "viewer"


class ScimToken(SQLModel, table=True):
    """Bearer token for an IdP's SCIM 2.0 client. Provisions users into one company."""

    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True)
    name: str = ""
    company_id: int = Field(foreign_key="company.id", index=True)
    default_role: str = "viewer"
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    revoked: bool = False


class PromptSet(SQLModel, table=True):
    """A reusable library of the user's own test prompts (a "dataset") plus how to
    grade responses to them. Used to run custom-prompt evaluations against a target.
    Company-scoped; global-admin sets have company_id = None.

    grading shape:
      {"use_rubric": bool, "rubric": str,
       "must_not_contain": [str], "must_contain": [str],
       "severity": "critical|high|medium|low"}
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    name: str = ""
    description: str = ""
    prompts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    grading: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class NotifyChannel(SQLModel, table=True):
    """A destination for scan alerts (Slack / Teams / generic webhook). The URL may
    contain a secret token, so it is encrypted at rest. Company-scoped."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    name: str = ""
    kind: str = "webhook"            # slack | teams | webhook
    url_enc: str = Field(default="", sa_column=Column(Text))  # Fernet-encrypted URL
    on_complete: bool = True         # notify when any scan finishes
    min_risk: int = 0                # only notify when risk score >= this (0 = always)
    enabled: bool = True
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class TicketConfig(SQLModel, table=True):
    """Per-company issue-tracker integration (GitHub Issues / Jira). The config holds
    an API token, so it is encrypted at rest."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id", index=True)
    name: str = ""
    kind: str = "github"               # github | jira
    config_enc: str = Field(default="", sa_column=Column(Text))  # Fernet JSON
    enabled: bool = True
    auto_create: bool = False          # auto-file tickets for failing findings on completion
    min_severity: str = "high"         # auto-create threshold: critical|high|medium|low
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class Schedule(SQLModel, table=True):
    """A recurring campaign. The scheduler creates and starts a new Campaign from
    `template` (same shape as the create-campaign body: name/target/tools) each time
    it is due. freq shape: {"kind":"interval","minutes":N} | {"kind":"daily","at":"HH:MM"}
    | {"kind":"weekly","day":0-6,"at":"HH:MM"} (day 0 = Monday, times in UTC)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    name: str = ""
    template: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    freq: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = True
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    last_run_at: Optional[datetime] = None
    last_campaign_id: Optional[int] = None
    next_run_at: Optional[datetime] = Field(default=None, index=True)
    # Scheduled report delivery (email the report after each run)
    report_emails: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    report_format: str = "pdf"  # pdf | attestation
