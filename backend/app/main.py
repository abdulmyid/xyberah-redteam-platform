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
                      ci_routes, console_routes, demo_routes, modelaudit_routes,
                      notify_routes, prompts_routes, report_routes, schedule_routes,
                      scim_routes, settings_routes, sso_routes, target_routes,
                      tls_routes)
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("xyberah")

app = FastAPI(title="Xyberah API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with Session(engine) as session:
        try:
            bootstrap_global_admin(session)
        except RuntimeError as exc:
            log.warning("Admin bootstrap skipped: %s", exc)
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
          sso_routes.router, scim_routes.router):
    app.include_router(r)

# Uploaded company logos (served read-only; proxy also serves these)
settings = get_settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # pragma: no cover - safety net
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
