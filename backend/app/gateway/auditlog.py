"""Asynchronous, structured, tamper-evident audit trail for gateway traffic.

Request handlers call :meth:`AuditTrail.emit` (non-blocking). A background task
drains the queue in batches and, off the event loop:

* appends JSON lines to ``<data>/gateway/audit/gateway-<host>-<date>.jsonl``
  (mode 0600). Each record carries ``prev_hash`` and ``hash`` (SHA-256 over the
  canonical record), chained across files, so deleting or editing any line is
  detectable with :func:`verify_files`;
* inserts metadata rows into ``GatewayEvent`` for the dashboard;
* forwards CEF lines to the instance syslog/SIEM target when configured;
* optionally writes the record to stdout for container log collectors.

Records never contain prompt or response text.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, delete

from ..db import engine
from ..models import GatewayConsumer, GatewayEvent

log = logging.getLogger("xyberah.gateway.audit")
json_log = logging.getLogger("xyberah.gateway.access")

EVENT_FIELDS = ("request_id", "company_id", "consumer_id", "consumer_name", "client_ip", "route", "provider",
                "model", "stream", "status_code", "verdict", "guardrail_verdict", "dlp_verdict",
                "blocked_direction", "rules_tripped", "prompt_tokens", "completion_tokens", "tokens_used",
                "proxy_latency_ms", "upstream_latency_ms", "cache_hit", "error")


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in record.items() if k != "hash"}, sort_keys=True,
                      separators=(",", ":"), default=str)


def chain_hash(record: dict[str, Any]) -> str:
    """SHA-256 over a record (excluding its own ``hash``), which includes ``prev_hash``."""
    return hashlib.sha256(_canonical(record).encode()).hexdigest()


def audit_dir(data_dir: Path) -> Path:
    """Directory holding the JSONL audit files."""
    return data_dir / "gateway" / "audit"


def _last_hash(directory: Path, host: str) -> str:
    files = sorted(directory.glob(f"gateway-{host}-*.jsonl"))
    for f in reversed(files):
        try:
            with f.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 65536))
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            if lines:
                return str(json.loads(lines[-1]).get("hash", ""))
        except (OSError, ValueError):
            continue
    return ""


def verify_files(directory: Path) -> dict[str, Any]:
    """Verify the hash chain of every audit file, per gateway host."""
    hosts: dict[str, list[Path]] = {}
    for f in sorted(directory.glob("gateway-*.jsonl")):
        host = f.stem[len("gateway-"):].rsplit("-", 3)[0]
        hosts.setdefault(host, []).append(f)
    result: dict[str, Any] = {"valid": True, "files": 0, "records": 0, "hosts": {}}
    for host, files in hosts.items():
        prev: Optional[str] = None
        broken: Optional[dict[str, Any]] = None
        count = 0
        for f in files:
            result["files"] += 1
            with f.open("r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        broken = {"file": f.name, "line": lineno, "reason": "unparseable record"}
                        break
                    if prev is not None and rec.get("prev_hash") != prev:
                        broken = {"file": f.name, "line": lineno, "reason": "chain link mismatch"}
                        break
                    if chain_hash(rec) != rec.get("hash"):
                        broken = {"file": f.name, "line": lineno, "reason": "record hash mismatch"}
                        break
                    prev = rec.get("hash")
                    count += 1
            if broken:
                break
        result["records"] += count
        result["hosts"][host] = {"records": count, "valid": broken is None, "broken": broken}
        if broken:
            result["valid"] = False
    return result


def _cef(rec: dict[str, Any]) -> str:
    sev = {"blocked": 7, "rate_limited": 5, "error": 5, "masked": 4}.get(rec.get("verdict", ""), 3)
    rules = ",".join(rec.get("rules_tripped") or [])[:400].replace("=", r"\=")
    ext = (f"rt={rec.get('ts', '')} src={rec.get('client_ip', '')} suser={rec.get('consumer_name', '')} "
           f"cs1Label=company cs1={rec.get('company_id', '')} cs2Label=verdict cs2={rec.get('verdict', '')} "
           f"cs3Label=rules cs3={rules} cs4Label=model cs4={rec.get('model', '')} "
           f"cn1Label=tokens cn1={rec.get('tokens_used', 0)} cn2Label=latencyMs cn2={rec.get('proxy_latency_ms', 0)} "
           f"outcome={rec.get('status_code', '')} externalId={rec.get('request_id', '')}")
    return (f"<110>{rec.get('ts', '')} xyberah-gateway CEF:0|Xyberah|AIFirewall|1.0|"
            f"gw-{rec.get('verdict', '')}|LLM request {rec.get('verdict', '')}|{sev}|{ext}")


class AuditTrail:
    """Batched background writer for gateway audit records."""

    BATCH_MAX = 500
    BATCH_WAIT_S = 0.5
    QUEUE_MAX = 50_000
    PRUNE_EVERY_S = 3600.0

    def __init__(self, data_dir: Path, host: Optional[str] = None) -> None:
        self._dir = audit_dir(data_dir)
        self._host = (host or socket.gethostname()).replace("-", "_")[:40] or "gateway"
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._task: Optional[asyncio.Task[None]] = None
        self._prev = ""
        self._dropped = 0
        self._last_prune = 0.0
        self._syslog_cfg: dict[str, Any] = {}
        self._syslog_loaded = 0.0
        self.settings: dict[str, Any] = {}

    @property
    def dropped(self) -> int:
        """Records dropped because the queue was full (exposed in health)."""
        return self._dropped

    def start(self, settings: dict[str, Any]) -> None:
        """Prepare the audit directory, resume the hash chain and start the writer."""
        self.settings = settings
        self._dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._dir, 0o700)
        self._prev = _last_hash(self._dir, self._host)
        self._task = asyncio.create_task(self._run(), name="gateway-audit-writer")

    async def stop(self) -> None:
        """Drain pending records and stop the writer."""
        if self._task is None:
            return
        await self._queue.join()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def emit(self, event: dict[str, Any]) -> None:
        """Queue an audit record; never blocks or raises in the request path."""
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        record.update({k: event.get(k) for k in EVENT_FIELDS})
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 1000 == 1:
                log.error("audit queue full; %d records dropped so far", self._dropped)

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            batch = [first]
            deadline = time.monotonic() + self.BATCH_WAIT_S
            while len(batch) < self.BATCH_MAX:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), timeout))
                except asyncio.TimeoutError:
                    break
            try:
                await asyncio.to_thread(self._flush, batch)
            except Exception:  # noqa: BLE001 - the writer must survive any single failure
                log.exception("audit flush failed for %d records", len(batch))
            finally:
                for _ in batch:
                    self._queue.task_done()

    # ---- runs in a worker thread ------------------------------------------ #
    def _flush(self, batch: list[dict[str, Any]]) -> None:
        self._write_file(batch)
        self._write_db(batch)
        self._forward_syslog(batch)
        if self.settings.get("log_to_stdout", True):
            for rec in batch:
                json_log.info(json.dumps(rec, separators=(",", ":"), default=str))
        if time.monotonic() - self._last_prune > self.PRUNE_EVERY_S:
            self._last_prune = time.monotonic()
            self._prune()

    def _write_file(self, batch: list[dict[str, Any]]) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._dir / f"gateway-{self._host}-{day}.jsonl"
        lines: list[str] = []
        for rec in batch:
            rec["host"] = self._host
            rec["prev_hash"] = self._prev
            rec["hash"] = chain_hash(rec)
            self._prev = rec["hash"]
            lines.append(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _write_db(self, batch: list[dict[str, Any]]) -> None:
        last_used: dict[int, datetime] = {}
        with Session(engine) as s:
            for rec in batch:
                ts = datetime.fromisoformat(rec["ts"])
                s.add(GatewayEvent(ts=ts, **{k: rec.get(k) if rec.get(k) is not None else _default(k)
                                             for k in EVENT_FIELDS}))
                if rec.get("consumer_id"):
                    last_used[int(rec["consumer_id"])] = ts
            for cid, ts in last_used.items():
                consumer = s.get(GatewayConsumer, cid)
                if consumer is not None:
                    consumer.last_used_at = ts
                    s.add(consumer)
            s.commit()

    def _forward_syslog(self, batch: list[dict[str, Any]]) -> None:
        if time.monotonic() - self._syslog_loaded > 30:
            from ..audit import get_syslog

            try:
                self._syslog_cfg = get_syslog()
            except Exception:  # noqa: BLE001
                self._syslog_cfg = {}
            self._syslog_loaded = time.monotonic()
        cfg = self._syslog_cfg
        if not cfg.get("enabled") or not cfg.get("host"):
            return
        try:
            if cfg.get("protocol") == "tcp":
                with socket.create_connection((cfg["host"], int(cfg.get("port", 514))), timeout=2) as sock:
                    sock.sendall(b"".join(_cef(r).encode()[:2000] + b"\n" for r in batch))
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    for r in batch:
                        sock.sendto(_cef(r).encode()[:2000], (cfg["host"], int(cfg.get("port", 514))))
        except OSError as exc:
            log.debug("syslog forward failed: %s", exc)

    def _prune(self) -> None:
        days = int(self.settings.get("event_retention_days", 30) or 0)
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            with Session(engine) as s:
                s.exec(delete(GatewayEvent).where(GatewayEvent.ts < cutoff))
                s.commit()
        file_days = int(self.settings.get("file_retention_days", 0) or 0)
        if file_days > 0:
            cutoff_day = (datetime.now(timezone.utc) - timedelta(days=file_days)).strftime("%Y-%m-%d")
            for f in self._dir.glob(f"gateway-{self._host}-*.jsonl"):
                if f.stem[-10:] < cutoff_day:
                    try:
                        f.unlink()
                    except OSError:
                        pass


def _default(name: str) -> Any:
    if name in ("rules_tripped",):
        return []
    if name in ("stream", "cache_hit"):
        return False
    if name in ("status_code", "prompt_tokens", "completion_tokens", "tokens_used"):
        return 0
    if name in ("proxy_latency_ms", "upstream_latency_ms"):
        return 0.0
    if name in ("company_id", "consumer_id"):
        return None
    return ""
