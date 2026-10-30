"""Saved authenticated browser sessions (Playwright storageState), encrypted at rest."""
import json
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..crypto import decrypt, encrypt
from ..db import engine
from ..models import BrowserSession


def create_session(company_id: Optional[int], name: str, storage_json: str, user_id: int) -> BrowserSession:
    json.loads(storage_json)  # validate it is JSON (raises on bad input)
    row = BrowserSession(company_id=company_id, name=name or "session",
                         data_enc=encrypt(storage_json), created_by=user_id)
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def materialize(session_id: int, company_id: Optional[int], dest_dir: Path) -> Optional[str]:
    """Decrypt a saved session to <dest_dir>/session.json; return the path or None."""
    with Session(engine) as s:
        row = s.get(BrowserSession, session_id)
    if not row:
        return None
    if company_id is not None and row.company_id not in (None, company_id):
        return None  # tenancy guard
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "session.json"
    path.write_text(decrypt(row.data_enc), encoding="utf-8")
    path.chmod(0o600)
    return str(path)
