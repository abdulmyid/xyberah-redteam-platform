"""Operational health, cleanup, audit rotation, and syslog push (global admin)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import audit, ops
from ..auth import global_admin
from ..models import User

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/health")
def get_health(user: User = Depends(global_admin)):
    return ops.health()


class CleanupIn(BaseModel):
    events_days: int = 0
    clear_outbox: bool = False
    vacuum: bool = False


@router.post("/cleanup")
def run_cleanup(body: CleanupIn, user: User = Depends(global_admin)):
    return ops.cleanup(events_days=body.events_days, clear_outbox=body.clear_outbox, vacuum=body.vacuum)


class RotateIn(BaseModel):
    before_days: int = 90


@router.post("/audit/rotate")
def rotate_audit(body: RotateIn, user: User = Depends(global_admin)):
    return audit.rotate(body.before_days)


class SyslogIn(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 514
    protocol: str = "udp"  # udp | tcp


@router.get("/syslog")
def get_syslog(user: User = Depends(global_admin)):
    return audit.get_syslog()


@router.put("/syslog")
def set_syslog(body: SyslogIn, user: User = Depends(global_admin)):
    return audit.save_syslog(body.model_dump())


@router.post("/syslog/test")
def test_syslog(body: SyslogIn, user: User = Depends(global_admin)):
    return audit.syslog_test(body.model_dump())
