"""Outbound email. SMTP settings come from the DB (set by a global admin in the
Settings UI). When SMTP is not configured, emails are written to
$XYBERAH_DATA_DIR/outbox/ as .eml files so invites and OTPs can be tested
without a mail server (the dev fallback)."""
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from .config import get_settings
from .crypto import decrypt, encrypt
from .db import engine
from .models import Setting

SMTP_KEY = "smtp"


def get_smtp() -> dict[str, Any]:
    with Session(engine) as s:
        row = s.get(Setting, SMTP_KEY)
        cfg = dict(row.value) if row and row.value else {}
    cfg.pop("password_enc", None)
    cfg["configured"] = bool(row and row.value and row.value.get("host"))
    return cfg


def save_smtp(values: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as s:
        row = s.get(Setting, SMTP_KEY)
        current = dict(row.value) if row and row.value else {}
        for k in ("host", "port", "username", "from_addr", "from_name", "use_tls"):
            if values.get(k) is not None:
                current[k] = values[k]
        if values.get("password"):
            current["password_enc"] = encrypt(values["password"])
        if row:
            row.value = current
        else:
            row = Setting(key=SMTP_KEY, value=current)
        s.add(row)
        s.commit()
    return get_smtp()


def save_email_settings_or_422(values: dict[str, Any]) -> dict[str, Any]:
    if "port" in values and not (1 <= int(values["port"]) <= 65535):
        from fastapi import HTTPException
        raise HTTPException(422, "port must be between 1 and 65535")
    return save_smtp(values)


def _smtp_raw() -> Optional[dict[str, Any]]:
    with Session(engine) as s:
        row = s.get(Setting, SMTP_KEY)
    if not row or not row.value or not row.value.get("host"):
        return None
    cfg = dict(row.value)
    cfg["password"] = decrypt(cfg.get("password_enc", "")) if cfg.get("password_enc") else ""
    return cfg


def send_email(to: str, subject: str, html: str, text: str = "") -> dict[str, Any]:
    cfg = _smtp_raw()
    msg = EmailMessage()
    from_name = (cfg or {}).get("from_name", "Xyberah")
    from_addr = (cfg or {}).get("from_addr") or "no-reply@xyberah.local"
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text or _strip(html))
    msg.add_alternative(html, subtype="html")

    if not cfg:
        return _write_outbox(to, subject, msg)
    port = int(cfg.get("port", 587))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(cfg["host"], port, context=context, timeout=20) as server:
            _login_send(server, cfg, msg)
    else:
        with smtplib.SMTP(cfg["host"], port, timeout=20) as server:
            if cfg.get("use_tls", True):
                server.starttls(context=context)
            _login_send(server, cfg, msg)
    return {"delivered": "smtp", "to": to}


def _login_send(server: smtplib.SMTP, cfg: dict[str, Any], msg: EmailMessage) -> None:
    if cfg.get("username"):
        server.login(cfg["username"], cfg.get("password", ""))
    server.send_message(msg)


def _write_outbox(to: str, subject: str, msg: EmailMessage) -> dict[str, Any]:
    outbox = get_settings().data_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = outbox / f"{stamp}-{to.replace('@', '_at_')}.eml"
    path.write_bytes(bytes(msg))
    return {"delivered": "outbox", "to": to, "file": str(path)}


def _strip(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()
