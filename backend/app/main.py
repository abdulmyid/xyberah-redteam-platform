"""Xyberah backend: FastAPI app wiring, startup bootstrap, static mounts."""
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .auth import bootstrap_global_admin
from .config import get_settings
from .db import engine, init_db
from .routers import (admin_routes, audit_routes, auth_routes, campaign_routes,
                      ci_routes, console_routes, demo_routes, governance_routes,
                      modelaudit_routes, notify_routes, prompts_routes, report_routes,
                      schedule_routes, scim_routes, settings_routes, sso_routes,
                      target_routes, tls_routes)
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xyberah")

API_DESCRIPTION = """
Xyberah is a self-hosted, multi-tenant AI red-teaming and security-evaluation platform.

**Authentication**
- **Browser/session**: log in at `/login`; the session is an HttpOnly cookie. State-changing
  requests must send `X-Requested-With: xyberah` (CSRF).
- **Automation/CI**: send `Authorization: Bearer <api-token>` (create tokens in Settings →
  API tokens). The token acts as its creating user, so tenancy and role apply.
- **SSO**: OIDC and SAML sign-in (Settings → SSO & SCIM); SCIM 2.0 at `/scim/v2` for
  IdP-driven provisioning (separate SCIM bearer token).

**Tenancy**: every object is scoped by company. Global admins act across companies; everyone
else is confined to their own.

Interactive docs: this page. Raw schema: `/api/openapi.json`.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Login, first-time setup, 2FA (TOTP + email OTP), current user."},
    {"name": "campaigns", "description": "Create/run/pause/stop campaigns; findings, triage, retest, drift diff, live event stream."},
    {"name": "prompts", "description": "Prompts & Datasets library, AI attack-pack generation, and traffic (OTLP/JSONL/CSV) import."},
    {"name": "schedules", "description": "Recurring campaigns (daily/weekly/interval) with run-now."},
    {"name": "reports", "description": "HTML/PDF/JSON/CSV reports, CEF (SIEM) export, signed compliance attestation, share links."},
    {"name": "modelaudit", "description": "Scan model files (pickle/safetensors/…) for malicious code and unsafe deserialization."},
    {"name": "console", "description": "Interactive single-prompt probing of any target."},
    {"name": "notify", "description": "Alert channels (Slack/Teams/webhook) fired on scan completion."},
    {"name": "ci", "description": "CI/CD quality gate and API tokens."},
    {"name": "governance", "description": "Per-company PII redaction, retention, and cost/token budgets."},
    {"name": "sso", "description": "OIDC/SAML sign-in and admin config (domain maps, SCIM tokens)."},
    {"name": "scim", "description": "SCIM 2.0 user provisioning (IdP-driven)."},
    {"name": "targets", "description": "Target connection test, saved targets, browser sessions."},
    {"name": "settings", "description": "Company/user/branding/SMTP/scanner settings."},
    {"name": "tls", "description": "TLS certificate upload/management."},
    {"name": "audit", "description": "Hash-chained audit log and integrity verification."},
]

app = FastAPI(
    title="Xyberah API",
    version="2.0.0",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={"docExpansion": "none", "persistAuthorization": True},
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with Session(engine) as session:
        try:
            bootstrap_global_admin(session)
        except RuntimeError as exc:
            log.warning("Admin bootstrap skipped: %s", exc)
    from .orchestrator import runner
    recovered = runner.recover_interrupted()
    if recovered:
        log.warning("Recovered %d campaign(s) interrupted by a restart", recovered)
    start_scheduler()
    log.info("Xyberah backend ready")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.middleware("http")
async def _audit(request, call_next):
    response = await call_next(request)
    try:
        from .audit import record
        record(request, response.status_code)
    except Exception:  # auditing must never break a request
        log.exception("audit record failed")
    return response


for r in (auth_routes.router, admin_routes.router, campaign_routes.router,
          report_routes.router, settings_routes.router, tls_routes.router,
          audit_routes.router, demo_routes.router, target_routes.router,
          ci_routes.router, modelaudit_routes.router, prompts_routes.router,
          schedule_routes.router, notify_routes.router, console_routes.router,
          sso_routes.router, scim_routes.router, governance_routes.router):
    app.include_router(r)

# Uploaded company logos (served read-only; proxy also serves these)
settings = get_settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # pragma: no cover - safety net
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
