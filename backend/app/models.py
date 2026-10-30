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
