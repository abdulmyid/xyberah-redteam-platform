"""AI Firewall administration: upstream providers, policies & rules, consumer keys,
traffic log, statistics, policy playground and gateway settings. Tenancy-scoped."""
import ipaddress
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import company_scope, global_admin, require_role
from ..config import get_settings as platform_settings
from ..crypto import encrypt
from ..db import get_session
from ..gateway import engine as gw_engine
from ..gateway.auditlog import audit_dir, verify_files
from ..gateway.detectors import ENTITY_GROUPS
from ..gateway.store import get_settings, new_consumer_key, policy_rules, rule_to_dict, save_settings
from ..gateway.toxicity import TOXICITY_CATEGORIES
from ..models import (GatewayConsumer, GatewayEvent, GatewayPolicy, GatewayProvider, GatewayRule, Role,
                      SavedTarget, User, utcnow)

router = APIRouter(prefix="/api/gateway", tags=["gateway"])
PROVIDER_KINDS = ("openai", "anthropic", "openai_compatible", "azure_openai")
INTERNAL_HOSTS = {"localhost", "redis", "backend", "proxy", "gateway", "metadata.google.internal"}
GATEWAY_INTERNAL_URL = os.getenv("XYBERAH_GATEWAY_INTERNAL_URL", "http://gateway:8080")


# ---- helpers --------------------------------------------------------------- #
def _scoped(model: Any, row_id: int, user: User, session: Session, what: str) -> Any:
    row = session.get(model, row_id)
    scope = company_scope(user)
    if row is None or (scope is not None and row.company_id != scope):
        raise HTTPException(404, f"No such {what}")
    return row


def _scope_query(model: Any, user: User) -> Any:
    q = select(model)
    scope = company_scope(user)
    if scope is not None:
        q = q.where(model.company_id == scope)
    return q


def _validate_base_url(url: str) -> str:
    """Reject non-HTTP schemes and loopback / link-local / internal-service targets (SSRF)."""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(422, "base_url must be an http(s) URL")
    host = parsed.hostname.lower()
    if host in INTERNAL_HOSTS or (host.endswith(".internal") and host != "host.docker.internal"):
        raise HTTPException(422, "base_url may not point at internal platform services")
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        addrs = set()  # unresolvable now (e.g. split DNS); re-checked by the network at request time
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(422, "base_url resolves to a loopback/link-local address")
    return url


def _touch_policy(session: Session, policy_id: int) -> None:
    policy = session.get(GatewayPolicy, policy_id)
    if policy is not None:
        policy.updated_at = utcnow()
        session.add(policy)


# ---- catalog / status / settings ------------------------------------------- #
@router.get("/catalog")
def catalog(user: User = Depends(require_role(Role.analyst))) -> dict[str, Any]:
    """Rule kinds, actions, DLP entities and toxicity categories for the rule builder."""
    return {
        "kinds": [
            {"id": "injection", "label": "Prompt injection & jailbreak", "classifier": True},
            {"id": "toxicity", "label": "Toxic content", "classifier": True},
            {"id": "code", "label": "Code generation", "classifier": True},
            {"id": "dlp", "label": "Data loss prevention (PII / financial / secrets)", "classifier": False},
            {"id": "keywords", "label": "Custom secret keywords", "classifier": False},
            {"id": "regex", "label": "Custom pattern (regex)", "classifier": False},
        ],
        "span_actions": list(gw_engine.SPAN_ACTIONS),
        "classifier_actions": list(gw_engine.CLASSIFIER_ACTIONS),
        "directions": list(gw_engine.DIRECTIONS),
        "entity_groups": ENTITY_GROUPS,
        "toxicity_categories": TOXICITY_CATEGORIES,
        "provider_kinds": list(PROVIDER_KINDS),
    }


@router.get("/status")
def status(user: User = Depends(require_role(Role.analyst))) -> dict[str, Any]:
    """Gateway liveness (internal probe) and the public base URL for client setup."""
    health: dict[str, Any] = {"reachable": False}
    try:
        r = httpx.get(f"{GATEWAY_INTERNAL_URL}/healthz", timeout=2.0)
        if r.status_code == 200:
            health = {"reachable": True, **r.json()}
    except httpx.HTTPError as exc:
        health["error"] = type(exc).__name__
    return {"health": health, "public_base_url": get_settings().get("public_base_url", ""),
            "internal_url": GATEWAY_INTERNAL_URL}


class GatewaySettingsIn(BaseModel):
    event_retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    file_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    stream_holdback: Optional[int] = Field(default=None, ge=16, le=4096)
    max_body_kb: Optional[int] = Field(default=None, ge=16, le=65536)
    log_to_stdout: Optional[bool] = None
    public_base_url: Optional[str] = None


@router.get("/settings")
def read_settings(user: User = Depends(global_admin)) -> dict[str, Any]:
    return get_settings()


@router.put("/settings")
def write_settings(body: GatewaySettingsIn, user: User = Depends(global_admin)) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True)
    if "public_base_url" in values:
        url = values["public_base_url"].strip().rstrip("/")
        if url and urlparse(url).scheme not in ("http", "https"):
            raise HTTPException(422, "public_base_url must be an http(s) URL")
        values["public_base_url"] = url
    return save_settings(values)


@router.get("/audit/verify")
def verify_audit(user: User = Depends(global_admin)) -> dict[str, Any]:
    """Verify the hash chain of the gateway's JSONL audit files."""
    directory = audit_dir(platform_settings().data_dir)
    if not directory.exists():
        return {"valid": True, "files": 0, "records": 0, "hosts": {}}
    return verify_files(directory)


# ---- providers ------------------------------------------------------------- #
class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "openai"
    base_url: str = ""
    api_key: str = ""                      # blank on update = keep existing
    api_version: str = ""
    model_map: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=5, le=900)
    enabled: bool = True


def _provider_out(p: GatewayProvider) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "api_version": p.api_version,
            "model_map": p.model_map or {}, "timeout_seconds": p.timeout_seconds, "enabled": p.enabled,
            "has_key": bool(p.api_key_enc), "created_at": p.created_at}


def _check_provider(body: ProviderIn) -> str:
    if body.kind not in PROVIDER_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(PROVIDER_KINDS)}")
    if body.kind in ("openai_compatible", "azure_openai") and not body.base_url.strip():
        raise HTTPException(422, "base_url is required for this provider kind")
    if len(body.model_map) > 200:
        raise HTTPException(422, "too many model aliases")
    return _validate_base_url(body.base_url)


@router.get("/providers")
def list_providers(user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_provider_out(p) for p in session.exec(_scope_query(GatewayProvider, user)).all()]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    base_url = _check_provider(body)
    p = GatewayProvider(company_id=user.company_id, name=body.name.strip(), kind=body.kind, base_url=base_url,
                        api_key_enc=encrypt(body.api_key.strip()) if body.api_key.strip() else "",
                        api_version=body.api_version.strip(), model_map=body.model_map,
                        timeout_seconds=body.timeout_seconds, enabled=body.enabled, created_by=user.id)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _provider_out(p)


@router.put("/providers/{pid}")
def update_provider(pid: int, body: ProviderIn, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _scoped(GatewayProvider, pid, user, session, "provider")
    p.base_url = _check_provider(body)
    p.name, p.kind, p.api_version = body.name.strip(), body.kind, body.api_version.strip()
    p.model_map, p.timeout_seconds, p.enabled = body.model_map, body.timeout_seconds, body.enabled
    if body.api_key.strip():
        p.api_key_enc = encrypt(body.api_key.strip())
    session.add(p)
    session.commit()
    session.refresh(p)
    return _provider_out(p)


@router.delete("/providers/{pid}")
def delete_provider(pid: int, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, bool]:
    p = _scoped(GatewayProvider, pid, user, session, "provider")
    for c in session.exec(_scope_query(GatewayConsumer, user)).all():
        if pid in (c.provider_ids or []):
            c.provider_ids = [x for x in c.provider_ids if x != pid]
            session.add(c)
    session.delete(p)
    session.commit()
    return {"ok": True}


# ---- policies & rules ------------------------------------------------------ #
class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    block_message: str = Field(default="This request was blocked by the AI firewall security policy.",
                               min_length=1, max_length=500)
    block_response: str = "error"
    restore_pseudonyms: bool = True
    stream_holdback: int = Field(default=0, ge=0, le=4096)
    template: str = "recommended"          # create only: recommended | blank


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    direction: str = "inbound"
    action: str = "block"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)


def _policy_out(p: GatewayPolicy, session: Session, with_rules: bool = False) -> dict[str, Any]:
    rules = policy_rules(session, p.id)
    out: dict[str, Any] = {"id": p.id, "name": p.name, "description": p.description,
                           "block_message": p.block_message, "block_response": p.block_response,
                           "restore_pseudonyms": p.restore_pseudonyms, "stream_holdback": p.stream_holdback,
                           "rule_count": len(rules), "updated_at": p.updated_at,
                           "consumers": len(session.exec(select(GatewayConsumer.id)
                                                         .where(GatewayConsumer.policy_id == p.id)).all())}
    if with_rules:
        out["rules"] = sorted(rules, key=lambda r: (r["priority"], r["id"]))
    return out


def _apply_policy_fields(p: GatewayPolicy, body: PolicyIn) -> None:
    if body.block_response not in ("error", "message"):
        raise HTTPException(422, "block_response must be 'error' or 'message'")
    p.name, p.description = body.name.strip(), body.description.strip()
    p.block_message, p.block_response = body.block_message.strip(), body.block_response
    p.restore_pseudonyms, p.stream_holdback = body.restore_pseudonyms, body.stream_holdback
    p.updated_at = utcnow()


def _new_rule(policy: GatewayPolicy, body: RuleIn) -> GatewayRule:
    try:
        cfg = gw_engine.validate_rule(body.kind, body.direction, body.action, body.config)
    except gw_engine.RuleError as exc:
        raise HTTPException(422, str(exc)) from exc
    return GatewayRule(company_id=policy.company_id, policy_id=policy.id, name=body.name.strip(), kind=body.kind,
                       direction=body.direction, action=body.action, config=cfg, enabled=body.enabled,
                       priority=body.priority)


@router.get("/policies")
def list_policies(user: User = Depends(require_role(Role.analyst)),
                  session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_policy_out(p, session) for p in session.exec(_scope_query(GatewayPolicy, user)).all()]


@router.post("/policies", status_code=201)
def create_policy(body: PolicyIn, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    p = GatewayPolicy(company_id=user.company_id, created_by=user.id)
    _apply_policy_fields(p, body)
    session.add(p)
    session.commit()
    session.refresh(p)
    if body.template == "recommended":
        for spec in gw_engine.recommended_rules():
            session.add(_new_rule(p, RuleIn(**spec)))
        session.commit()
    return _policy_out(p, session, with_rules=True)


@router.get("/policies/{pid}")
def get_policy(pid: int, user: User = Depends(require_role(Role.analyst)),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    return _policy_out(_scoped(GatewayPolicy, pid, user, session, "policy"), session, with_rules=True)


@router.put("/policies/{pid}")
def update_policy(pid: int, body: PolicyIn, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _scoped(GatewayPolicy, pid, user, session, "policy")
    _apply_policy_fields(p, body)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _policy_out(p, session, with_rules=True)


@router.delete("/policies/{pid}")
def delete_policy(pid: int, user: User = Depends(require_role(Role.company_admin)),
                  session: Session = Depends(get_session)) -> dict[str, bool]:
    p = _scoped(GatewayPolicy, pid, user, session, "policy")
    in_use = session.exec(select(GatewayConsumer.id).where(GatewayConsumer.policy_id == pid)).first()
    if in_use is not None:
        raise HTTPException(409, "Policy is assigned to consumers; reassign them first")
    for r in session.exec(select(GatewayRule).where(GatewayRule.policy_id == pid)).all():
        session.delete(r)
    session.delete(p)
    session.commit()
    return {"ok": True}


@router.post("/policies/{pid}/rules", status_code=201)
def add_rule(pid: int, body: RuleIn, user: User = Depends(require_role(Role.company_admin)),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    p = _scoped(GatewayPolicy, pid, user, session, "policy")
    if len(policy_rules(session, pid)) >= 100:
        raise HTTPException(422, "A policy may have at most 100 rules")
    rule = _new_rule(p, body)
    session.add(rule)
    _touch_policy(session, pid)
    session.commit()
    session.refresh(rule)
    return rule_to_dict(rule)


@router.put("/rules/{rid}")
def update_rule(rid: int, body: RuleIn, user: User = Depends(require_role(Role.company_admin)),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    rule = _scoped(GatewayRule, rid, user, session, "rule")
    try:
        cfg = gw_engine.validate_rule(body.kind, body.direction, body.action, body.config)
    except gw_engine.RuleError as exc:
        raise HTTPException(422, str(exc)) from exc
    rule.name, rule.kind, rule.direction, rule.action = body.name.strip(), body.kind, body.direction, body.action
    rule.config, rule.enabled, rule.priority, rule.updated_at = cfg, body.enabled, body.priority, utcnow()
    session.add(rule)
    _touch_policy(session, rule.policy_id)
    session.commit()
    session.refresh(rule)
    return rule_to_dict(rule)


@router.delete("/rules/{rid}")
def delete_rule(rid: int, user: User = Depends(require_role(Role.company_admin)),
                session: Session = Depends(get_session)) -> dict[str, bool]:
    rule = _scoped(GatewayRule, rid, user, session, "rule")
    _touch_policy(session, rule.policy_id)
    session.delete(rule)
    session.commit()
    return {"ok": True}


class PlaygroundIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    direction: str = "inbound"
    role: str = "user"


@router.post("/policies/{pid}/test")
def test_policy(pid: int, body: PlaygroundIn, user: User = Depends(require_role(Role.analyst)),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    """Run a policy against sample text exactly as the gateway would (no traffic is sent)."""
    _scoped(GatewayPolicy, pid, user, session, "policy")
    if body.direction not in ("inbound", "outbound"):
        raise HTTPException(422, "direction must be inbound or outbound")
    rules = policy_rules(session, pid)
    t0 = time.perf_counter()
    outcome = gw_engine.scan([(body.role, body.text)], rules, body.direction,
                             secret=platform_settings().secret_key)
    elapsed = (time.perf_counter() - t0) * 1000
    guard, dlp = gw_engine.verdicts(outcome.detections)
    return {"blocked": outcome.blocked, "output": outcome.texts[0], "guardrail_verdict": guard,
            "dlp_verdict": dlp, "latency_ms": round(elapsed, 2),
            "detections": [{**d.to_dict(), "match": body.text[d.start:d.end] if d.start >= 0 else ""}
                           for d in outcome.detections]}


# ---- consumers ------------------------------------------------------------- #
class ConsumerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    policy_id: Optional[int] = None
    provider_ids: list[int] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    requests_per_minute: int = Field(default=60, ge=0, le=1_000_000)
    tokens_per_minute: int = Field(default=0, ge=0, le=1_000_000_000)
    cache_enabled: bool = False
    cache_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    enabled: bool = True
    create_target: bool = False            # create only: also save a red-team target for this key
    target_model: str = ""


def _consumer_out(c: GatewayConsumer) -> dict[str, Any]:
    return {"id": c.id, "name": c.name, "key_prefix": c.key_prefix, "policy_id": c.policy_id,
            "provider_ids": c.provider_ids or [], "allowed_models": c.allowed_models or [],
            "requests_per_minute": c.requests_per_minute, "tokens_per_minute": c.tokens_per_minute,
            "cache_enabled": c.cache_enabled, "cache_ttl_seconds": c.cache_ttl_seconds, "enabled": c.enabled,
            "created_at": c.created_at, "last_used_at": c.last_used_at}


def _check_refs(body: ConsumerIn, user: User, session: Session) -> None:
    if body.policy_id is not None:
        _scoped(GatewayPolicy, body.policy_id, user, session, "policy")
    for pid in body.provider_ids:
        _scoped(GatewayProvider, pid, user, session, "provider")
    if len(body.allowed_models) > 200:
        raise HTTPException(422, "too many allowed models")


def _apply_consumer(c: GatewayConsumer, body: ConsumerIn) -> None:
    c.name, c.policy_id = body.name.strip(), body.policy_id
    c.provider_ids = list(dict.fromkeys(body.provider_ids))
    c.allowed_models = [m.strip() for m in body.allowed_models if m.strip()]
    c.requests_per_minute, c.tokens_per_minute = body.requests_per_minute, body.tokens_per_minute
    c.cache_enabled, c.cache_ttl_seconds, c.enabled = body.cache_enabled, body.cache_ttl_seconds, body.enabled


@router.get("/consumers")
def list_consumers(user: User = Depends(require_role(Role.company_admin)),
                   session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_consumer_out(c) for c in session.exec(_scope_query(GatewayConsumer, user)).all()]


@router.post("/consumers", status_code=201)
def create_consumer(body: ConsumerIn, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    _check_refs(body, user, session)
    target_model = body.target_model.strip() or (body.allowed_models[0].strip() if body.allowed_models else "")
    if body.create_target and not target_model:
        raise HTTPException(422, "target_model is required to create a red-team target")
    key, prefix, key_hash = new_consumer_key()
    c = GatewayConsumer(company_id=user.company_id, key_prefix=prefix, key_hash=key_hash, created_by=user.id)
    _apply_consumer(c, body)
    session.add(c)
    session.commit()
    session.refresh(c)
    out = _consumer_out(c)
    out["api_key"] = key  # shown once
    if body.create_target:
        model = target_model
        target = {"type": "http", "label": f"AI Firewall · {c.name}", "model": model, "system_prompt": "",
                  "http": {"url": f"{GATEWAY_INTERNAL_URL}/v1/chat/completions", "method": "POST",
                           "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                       "X-Xyberah-Block-Mode": "message"},
                           "body": {"model": model, "messages": [{"role": "user", "content": "{{prompt}}"}]},
                           "response_path": "choices.0.message.content"}}
        st = SavedTarget(company_id=user.company_id, name=f"AI Firewall · {c.name}", target_type="http",
                         config_enc=encrypt(json.dumps(target)), created_by=user.id)
        session.add(st)
        session.commit()
        session.refresh(st)
        out["saved_target_id"] = st.id
    return out


@router.put("/consumers/{cid}")
def update_consumer(cid: int, body: ConsumerIn, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    c = _scoped(GatewayConsumer, cid, user, session, "consumer")
    _check_refs(body, user, session)
    _apply_consumer(c, body)
    session.add(c)
    session.commit()
    session.refresh(c)
    return _consumer_out(c)


@router.post("/consumers/{cid}/rotate")
def rotate_consumer(cid: int, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    """Issue a new key; the old key stops working within a few seconds."""
    c = _scoped(GatewayConsumer, cid, user, session, "consumer")
    key, prefix, key_hash = new_consumer_key()
    c.key_prefix, c.key_hash = prefix, key_hash
    session.add(c)
    session.commit()
    session.refresh(c)
    return {**_consumer_out(c), "api_key": key}


@router.delete("/consumers/{cid}")
def delete_consumer(cid: int, user: User = Depends(require_role(Role.company_admin)),
                    session: Session = Depends(get_session)) -> dict[str, bool]:
    session.delete(_scoped(GatewayConsumer, cid, user, session, "consumer"))
    session.commit()
    return {"ok": True}


# ---- traffic & stats ------------------------------------------------------- #
def _event_out(e: GatewayEvent) -> dict[str, Any]:
    return {"id": e.id, "ts": e.ts, "request_id": e.request_id, "consumer_id": e.consumer_id,
            "consumer_name": e.consumer_name, "client_ip": e.client_ip, "route": e.route, "provider": e.provider,
            "model": e.model, "stream": e.stream, "status_code": e.status_code, "verdict": e.verdict,
            "guardrail_verdict": e.guardrail_verdict, "dlp_verdict": e.dlp_verdict,
            "blocked_direction": e.blocked_direction, "rules_tripped": e.rules_tripped or [],
            "prompt_tokens": e.prompt_tokens, "completion_tokens": e.completion_tokens,
            "tokens_used": e.tokens_used, "proxy_latency_ms": e.proxy_latency_ms,
            "upstream_latency_ms": e.upstream_latency_ms, "cache_hit": e.cache_hit, "error": e.error}


@router.get("/events")
def list_events(verdict: Optional[str] = None, consumer_id: Optional[int] = None, q: str = "",
                hours: int = Query(default=24, ge=1, le=24 * 365), offset: int = Query(default=0, ge=0),
                limit: int = Query(default=50, ge=1, le=500), user: User = Depends(require_role(Role.analyst)),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    conds = [GatewayEvent.ts >= since]
    scope = company_scope(user)
    if scope is not None:
        conds.append(GatewayEvent.company_id == scope)
    if verdict:
        conds.append(GatewayEvent.verdict == verdict)
    if consumer_id is not None:
        conds.append(GatewayEvent.consumer_id == consumer_id)
    if q.strip():
        like = f"%{q.strip()}%"
        conds.append(GatewayEvent.request_id.like(like) | GatewayEvent.model.like(like)  # type: ignore[union-attr]
                     | GatewayEvent.client_ip.like(like) | GatewayEvent.consumer_name.like(like))  # type: ignore[union-attr]
    total = session.exec(select(func.count()).select_from(GatewayEvent).where(*conds)).one()
    rows = session.exec(select(GatewayEvent).where(*conds).order_by(GatewayEvent.id.desc())
                        .offset(offset).limit(limit)).all()
    return {"items": [_event_out(e) for e in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/stats")
def stats(hours: int = Query(default=24, ge=1, le=24 * 90), user: User = Depends(require_role(Role.analyst)),
          session: Session = Depends(get_session)) -> dict[str, Any]:
    """Totals, verdict mix, latency percentiles, top rules and an hourly series."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = select(GatewayEvent.ts, GatewayEvent.verdict, GatewayEvent.rules_tripped, GatewayEvent.proxy_latency_ms,
               GatewayEvent.upstream_latency_ms, GatewayEvent.tokens_used, GatewayEvent.cache_hit,
               GatewayEvent.blocked_direction, GatewayEvent.dlp_verdict).where(GatewayEvent.ts >= since)
    scope = company_scope(user)
    if scope is not None:
        q = q.where(GatewayEvent.company_id == scope)
    rows = session.exec(q.limit(200_000)).all()
    verdicts: dict[str, int] = {}
    rules: dict[str, int] = {}
    latencies: list[float] = []
    overhead: list[float] = []
    buckets: dict[str, dict[str, int]] = {}
    tokens = cache_hits = inbound_blocks = outbound_blocks = dlp_masked = 0
    for ts, verdict, tripped, lat, up, tok, hit, direction, dlp in rows:
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        for r in tripped or []:
            rules[r] = rules.get(r, 0) + 1
        latencies.append(float(lat or 0))
        if up:
            overhead.append(max(0.0, float(lat or 0) - float(up)))
        tokens += int(tok or 0)
        cache_hits += int(bool(hit))
        inbound_blocks += int(direction == "inbound")
        outbound_blocks += int(direction == "outbound")
        dlp_masked += int(dlp == "masked")
        stamp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        hour = stamp.strftime("%Y-%m-%dT%H:00")
        b = buckets.setdefault(hour, {"requests": 0, "blocked": 0, "masked": 0})
        b["requests"] += 1
        b["blocked"] += int(verdict == "blocked")
        b["masked"] += int(verdict == "masked")

    def pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1) + 0.5))], 2)

    total = len(rows)
    return {
        "hours": hours, "total": total, "verdicts": verdicts, "tokens": tokens,
        "cache_hit_rate": round(cache_hits / total, 4) if total else 0.0,
        "inbound_blocks": inbound_blocks, "outbound_blocks": outbound_blocks, "dlp_masked": dlp_masked,
        "latency_ms": {"p50": pct(latencies, 0.5), "p95": pct(latencies, 0.95), "p99": pct(latencies, 0.99)},
        "gateway_overhead_ms": {"p50": pct(overhead, 0.5), "p95": pct(overhead, 0.95)},
        "top_rules": sorted(({"rule": k, "count": v} for k, v in rules.items()), key=lambda x: -x["count"])[:10],
        "series": [{"hour": h, **v} for h, v in sorted(buckets.items())],
    }
