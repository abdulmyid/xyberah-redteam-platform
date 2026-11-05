"""Gateway configuration access shared by the gateway process and the platform API.

The gateway resolves a consumer API key into a *bundle* (consumer, policy rules,
upstream providers with decrypted keys) and caches it briefly, so configuration
changes made in the UI take effect within ``BUNDLE_TTL`` seconds without a restart.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

from ..crypto import decrypt
from ..db import engine
from ..models import GatewayConsumer, GatewayPolicy, GatewayProvider, GatewayRule, Setting

SETTINGS_KEY = "gateway"
KEY_PREFIX = "xgw_"
BUNDLE_TTL = 5.0

DEFAULT_SETTINGS: dict[str, Any] = {
    "event_retention_days": 30,     # DB rows backing the UI
    "file_retention_days": 365,     # hash-chained JSONL audit files (0 = keep forever)
    "stream_holdback": 64,          # chars held back while scanning streamed output
    "max_body_kb": 2048,            # max request body
    "log_to_stdout": True,          # also emit each audit record as a JSON log line
    "public_base_url": "",          # shown in the UI quick start, e.g. https://ai.example.com:8080
}

PROVIDER_DEFAULT_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


def get_settings() -> dict[str, Any]:
    """Instance-wide gateway settings merged over defaults."""
    with Session(engine) as s:
        row = s.get(Setting, SETTINGS_KEY)
    stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def save_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Persist known settings keys (validated by the caller) and return the result."""
    with Session(engine) as s:
        row = s.get(Setting, SETTINGS_KEY)
        current = dict(row.value) if row and isinstance(row.value, dict) else {}
        for k, v in values.items():
            if k in DEFAULT_SETTINGS and v is not None:
                current[k] = v
        if row:
            row.value = current
        else:
            row = Setting(key=SETTINGS_KEY, value=current)
        s.add(row)
        s.commit()
    return get_settings()


def new_consumer_key() -> tuple[str, str, str]:
    """(plaintext key, display prefix, sha256 hash)."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[:12], hash_key(key)


def hash_key(key: str) -> str:
    """SHA-256 of a consumer key (keys are high-entropy, so no salt/KDF is needed)."""
    return hashlib.sha256(key.encode()).hexdigest()


def rule_to_dict(r: GatewayRule) -> dict[str, Any]:
    """Engine-ready dict for a rule row."""
    return {"id": r.id, "name": r.name, "kind": r.kind, "direction": r.direction, "action": r.action,
            "enabled": r.enabled, "priority": r.priority, "config": dict(r.config or {})}


def policy_rules(session: Session, policy_id: int) -> list[dict[str, Any]]:
    """All rules of a policy as engine dicts."""
    rows = session.exec(select(GatewayRule).where(GatewayRule.policy_id == policy_id)).all()
    return [rule_to_dict(r) for r in rows]


@dataclass
class ProviderCfg:
    """Upstream provider with its decrypted key (gateway-process memory only)."""

    id: int
    name: str
    kind: str
    base_url: str
    api_key: str
    api_version: str
    model_map: dict[str, str]
    timeout: int


@dataclass
class Bundle:
    """Everything the gateway needs to serve one consumer."""

    consumer_id: int
    consumer_name: str
    company_id: Optional[int]
    enabled: bool
    allowed_models: list[str]
    rpm: int
    tpm: int
    cache_enabled: bool
    cache_ttl: int
    policy_id: Optional[int]
    policy_version: str
    rules: list[dict[str, Any]]
    block_message: str
    block_response: str
    restore_pseudonyms: bool
    stream_holdback: int
    providers: list[ProviderCfg] = field(default_factory=list)


def load_bundle(key_hash: str) -> Optional[Bundle]:
    """Resolve a consumer key hash into a :class:`Bundle` (None if unknown)."""
    with Session(engine) as s:
        consumer = s.exec(select(GatewayConsumer).where(GatewayConsumer.key_hash == key_hash)).first()
        if consumer is None:
            return None
        rules: list[dict[str, Any]] = []
        policy: Optional[GatewayPolicy] = None
        if consumer.policy_id:
            policy = s.get(GatewayPolicy, consumer.policy_id)
            if policy is not None and policy.company_id == consumer.company_id:
                rules = policy_rules(s, policy.id)
            else:
                policy = None
        providers: list[ProviderCfg] = []
        for pid in consumer.provider_ids or []:
            p = s.get(GatewayProvider, int(pid))
            if p is None or not p.enabled or p.company_id != consumer.company_id:
                continue
            providers.append(ProviderCfg(
                id=p.id, name=p.name, kind=p.kind,
                base_url=(p.base_url or PROVIDER_DEFAULT_URLS.get(p.kind, "")).rstrip("/"),
                api_key=decrypt(p.api_key_enc) if p.api_key_enc else "",
                api_version=p.api_version, model_map={str(k): str(v) for k, v in (p.model_map or {}).items()},
                timeout=max(5, min(int(p.timeout_seconds or 120), 900))))
        version_src = json.dumps({"p": policy.updated_at.isoformat() if policy else "", "r": rules},
                                 sort_keys=True, default=str)
        return Bundle(
            consumer_id=consumer.id, consumer_name=consumer.name, company_id=consumer.company_id,
            enabled=consumer.enabled, allowed_models=list(consumer.allowed_models or []),
            rpm=int(consumer.requests_per_minute or 0), tpm=int(consumer.tokens_per_minute or 0),
            cache_enabled=bool(consumer.cache_enabled), cache_ttl=max(1, int(consumer.cache_ttl_seconds or 300)),
            policy_id=policy.id if policy else None,
            policy_version=hashlib.sha256(version_src.encode()).hexdigest()[:16],
            rules=rules,
            block_message=(policy.block_message if policy else "") or "Request blocked by the AI firewall.",
            block_response=(policy.block_response if policy else "error") or "error",
            restore_pseudonyms=bool(policy.restore_pseudonyms) if policy else True,
            stream_holdback=int(policy.stream_holdback or 0) if policy else 0,
            providers=providers)


class BundleCache:
    """Short-TTL cache of bundles keyed by consumer key hash (includes negatives)."""

    def __init__(self, ttl: float = BUNDLE_TTL) -> None:
        self._ttl = ttl
        self._items: dict[str, tuple[float, Optional[Bundle]]] = {}

    def get(self, key_hash: str) -> tuple[bool, Optional[Bundle]]:
        """(hit, bundle) — ``hit`` is False when the entry is missing or stale."""
        item = self._items.get(key_hash)
        if item is None or item[0] < time.monotonic():
            return False, None
        return True, item[1]

    def put(self, key_hash: str, bundle: Optional[Bundle]) -> None:
        """Cache ``bundle`` (or a negative result) for the TTL."""
        if len(self._items) > 10_000:
            self._items.clear()
        self._items[key_hash] = (time.monotonic() + self._ttl, bundle)
