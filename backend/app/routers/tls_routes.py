"""Frontend TLS certificate settings (global admin)."""
from fastapi import APIRouter, Depends, File, UploadFile

from ..auth import global_admin
from ..models import User
from ..tls_service import install, remove, status

router = APIRouter(prefix="/api/tls", tags=["tls"])

MAX_PEM = 64 * 1024


@router.get("")
def tls_status(admin: User = Depends(global_admin)):
    return status()


@router.post("")
def tls_upload(cert: UploadFile = File(...), key: UploadFile = File(...),
               admin: User = Depends(global_admin)):
    cert_pem = cert.file.read(MAX_PEM)
    key_pem = key.file.read(MAX_PEM)
    return install(cert_pem, key_pem)


@router.delete("")
def tls_reset(admin: User = Depends(global_admin)):
    """Revert to the automatic self-signed certificate."""
    return remove()
