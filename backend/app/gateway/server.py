"""Xyberah AI Firewall: asynchronous LLM reverse proxy (port 8080).

Request pipeline::

    authenticate consumer key -> size/JSON checks -> model allow-list + provider
    selection -> request rate limit -> inbound guardrails + DLP (process pool)
    -> token rate limit -> response cache -> upstream (httpx, streaming)
    -> outbound guardrails + DLP (sliding window for streams) -> client
    -> async hash-chained audit record

Clients use their gateway consumer key; provider keys never leave this process.
Supported APIs: OpenAI Chat Completions (``/v1/chat/completions``), OpenAI
Embeddings (``/v1/embeddings``) and Anthropic Messages (``/v1/messages``).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from sqlalchemy import text as sql_text

from ..config import get_settings as platform_settings
from ..db import engine as db_engine
from ..db import init_db
from . import engine
from .auditlog import AuditTrail
from .detectors import find_entities
from .engine import Detection
from .executor import DetectionExecutor
from .formats import (FORMAT_ANTHROPIC, FORMAT_EMBEDDINGS, FORMAT_OPENAI, SSEEvent, SSEParser,
                      estimate_tokens, get_path, request_slots, response_slots, set_path,
                      usage_from_response)
from .ratelimit import Limiter
from .store import DEFAULT_SETTINGS, Bundle, BundleCache, ProviderCfg, get_settings, hash_key, load_bundle
from .stream import StreamBlocked, StreamGuard

log = logging.getLogger("xyberah.gateway")
VERSION = "1.0.0"
BLOCK_TYPE = "xyberah_firewall_block"
FORMAT_KINDS: dict[str, tuple[str, ...]] = {
    FORMAT_OPENAI: ("openai", "openai_compatible", "azure_openai"),
    FORMAT_EMBEDDINGS: ("openai", "openai_compatible", "azure_openai"),
    FORMAT_ANTHROPIC: ("anthropic",),
}
LATENCY_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000)


# ---- process state --------------------------------------------------------- #
@dataclass
class Metrics:
    """In-process counters exposed in Prometheus text format."""

    requests: dict[str, int] = field(default_factory=dict)
    latency_counts: list[int] = field(default_factory=lambda: [0] * (len(LATENCY_BUCKETS_MS) + 1))
    latency_sum: float = 0.0
    tokens: int = 0
    cache_hits: int = 0

    def observe(self, verdict: str, latency_ms: float, tokens: int, cache_hit: bool) -> None:
        """Record one finished request."""
        self.requests[verdict] = self.requests.get(verdict, 0) + 1
        for i, bound in enumerate(LATENCY_BUCKETS_MS):
            if latency_ms <= bound:
                self.latency_counts[i] += 1
                break
        else:
            self.latency_counts[-1] += 1
        self.latency_sum += latency_ms
        self.tokens += tokens
        self.cache_hits += int(cache_hit)

    def render(self, audit_dropped: int, limiter_backend: str) -> str:
        """Prometheus exposition text."""
        lines = ["# TYPE xyberah_gateway_requests_total counter"]
        for verdict, n in sorted(self.requests.items()):
            lines.append(f'xyberah_gateway_requests_total{{verdict="{verdict}"}} {n}')
        lines.append("# TYPE xyberah_gateway_latency_ms histogram")
        cumulative = 0
        for bound, n in zip(LATENCY_BUCKETS_MS, self.latency_counts):
            cumulative += n
            lines.append(f'xyberah_gateway_latency_ms_bucket{{le="{bound:g}"}} {cumulative}')
        cumulative += self.latency_counts[-1]
        lines.append(f'xyberah_gateway_latency_ms_bucket{{le="+Inf"}} {cumulative}')
        lines.append(f"xyberah_gateway_latency_ms_sum {self.latency_sum:.3f}")
        lines.append(f"xyberah_gateway_latency_ms_count {cumulative}")
        lines.append("# TYPE xyberah_gateway_tokens_total counter")
        lines.append(f"xyberah_gateway_tokens_total {self.tokens}")
        lines.append("# TYPE xyberah_gateway_cache_hits_total counter")
        lines.append(f"xyberah_gateway_cache_hits_total {self.cache_hits}")
        lines.append("# TYPE xyberah_gateway_audit_dropped_total counter")
        lines.append(f"xyberah_gateway_audit_dropped_total {audit_dropped}")
        lines.append("# TYPE xyberah_gateway_redis_up gauge")
        lines.append(f"xyberah_gateway_redis_up {1 if limiter_backend == 'redis' else 0}")
        return "\n".join(lines) + "\n"


class GatewayState:
    """Long-lived resources shared by all requests."""

    def __init__(self) -> None:
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.secret = platform_settings().secret_key
        self.bundles = BundleCache()
        workers = os.getenv("XYBERAH_GATEWAY_WORKERS", "auto").strip().lower()
        self.executor = DetectionExecutor(None if workers in ("", "auto") else int(workers))
        self.limiter = Limiter(os.getenv("XYBERAH_REDIS_URL", ""))
        self.audit = AuditTrail(platform_settings().data_dir)
        self.metrics = Metrics()
        self.client: Optional[httpx.AsyncClient] = None
        self._refresh_task: Optional[asyncio.Task[None]] = None

    async def startup(self) -> None:
        """Initialize DB access, worker pool, Redis, audit writer and HTTP client."""
        await asyncio.to_thread(_init_database)
        self.settings = await asyncio.to_thread(get_settings)
        self.executor.start()
        await self.limiter.connect()
        self.audit.start(self.settings)
        self.client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=int(os.getenv("XYBERAH_GATEWAY_MAX_CONNECTIONS", "500")),
                                max_keepalive_connections=100, keepalive_expiry=30),
            follow_redirects=False, trust_env=True)
        self._refresh_task = asyncio.create_task(self._refresh_settings(), name="gateway-settings-refresh")
        log.info("Xyberah AI Firewall %s ready (workers=%d, limiter=%s)", VERSION,
                 self.executor.workers, self.limiter.backend)

    async def shutdown(self) -> None:
        """Release resources, draining the audit queue first."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await self.audit.stop()
        if self.client is not None:
            await self.client.aclose()
        await self.limiter.close()
        self.executor.shutdown()

    async def _refresh_settings(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                self.settings = await asyncio.to_thread(get_settings)
                self.audit.settings = self.settings
            except Exception:  # noqa: BLE001 - keep last known settings
                log.warning("gateway settings refresh failed", exc_info=True)

    async def bundle(self, key: str) -> Optional[Bundle]:
        """Consumer bundle for a plaintext key (cached briefly)."""
        key_hash = hash_key(key)
        hit, cached = self.bundles.get(key_hash)
        if hit:
            return cached
        loaded = await asyncio.to_thread(load_bundle, key_hash)
        self.bundles.put(key_hash, loaded)
        return loaded


def _init_database() -> None:
    """Create tables if needed (tolerating a concurrent create by the platform) and enable WAL."""
    for attempt in range(5):
        try:
            init_db()
            break
        except Exception:  # noqa: BLE001 - another process may be migrating
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
    with db_engine.begin() as conn:
        conn.execute(sql_text("PRAGMA journal_mode=WAL"))


STATE = GatewayState()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start and stop shared gateway resources."""
    await STATE.startup()
    try:
        yield
    finally:
        await STATE.shutdown()


app = FastAPI(title="Xyberah AI Firewall", version=VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


# ---- request context ------------------------------------------------------- #
@dataclass
class Ctx:
    """Per-request bookkeeping that becomes the audit record."""

    request_id: str
    t0: float
    client_ip: str
    route: str
    fmt: str
    bundle: Optional[Bundle] = None
    provider: Optional[ProviderCfg] = None
    model: str = ""
    stream: bool = False
    status_code: int = 200
    verdict: str = "allowed"
    blocked_direction: str = ""
    detections: list[Detection] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    upstream_ms: float = 0.0
    cache_hit: bool = False
    error: str = ""
    finished: bool = False
    deferred: bool = False  # a streaming body finishes the record itself

    def finish(self) -> None:
        """Emit the audit record and metrics exactly once."""
        if self.finished:
            return
        self.finished = True
        latency = (time.perf_counter() - self.t0) * 1000
        guard, dlp = engine.verdicts(self.detections)
        if self.verdict == "allowed" and dlp == "masked":
            self.verdict = "masked"
        tripped = sorted({d.rule_name for d in self.detections})
        tokens = self.prompt_tokens + self.completion_tokens
        STATE.audit.emit({
            "request_id": self.request_id, "client_ip": self.client_ip, "route": self.route,
            "company_id": self.bundle.company_id if self.bundle else None,
            "consumer_id": self.bundle.consumer_id if self.bundle else None,
            "consumer_name": self.bundle.consumer_name if self.bundle else "",
            "provider": self.provider.name if self.provider else "", "model": self.model,
            "stream": self.stream, "status_code": self.status_code, "verdict": self.verdict,
            "guardrail_verdict": guard, "dlp_verdict": dlp, "blocked_direction": self.blocked_direction,
            "rules_tripped": tripped, "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens, "tokens_used": tokens,
            "proxy_latency_ms": round(latency, 2), "upstream_latency_ms": round(self.upstream_ms, 2),
            "cache_hit": self.cache_hit, "error": self.error[:300],
        })
        STATE.metrics.observe(self.verdict, latency, tokens, self.cache_hit)


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        try:
            if ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback:
                return forwarded.split(",")[0].strip()[:64]
        except ValueError:
            pass
    return peer


def _consumer_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-api-key") or request.headers.get("api-key") or "").strip()


# ---- responses ------------------------------------------------------------- #
def _error(ctx: Ctx, status: int, err_type: str, message: str, extra: Optional[dict[str, Any]] = None,
           headers: Optional[dict[str, str]] = None) -> JSONResponse:
    ctx.status_code = status
    payload: dict[str, Any] = {"message": message, "type": err_type, "request_id": ctx.request_id}
    if extra:
        payload.update(extra)
    body: dict[str, Any] = ({"type": "error", "error": payload} if ctx.fmt == FORMAT_ANTHROPIC
                            else {"error": {**payload, "code": err_type}})
    return JSONResponse(body, status_code=status,
                        headers={"x-xyberah-request-id": ctx.request_id, **(headers or {})})


def _block_details(dets: list[Detection]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for d in dets:
        key = (d.rule_name, d.entity)
        if key in seen:
            continue
        seen.add(key)
        out.append({"rule": d.rule_name, "category": d.kind, "entity": d.entity, "score": round(d.score, 3)})
    return out


def _block_mode(request: Request, bundle: Bundle, fmt: str) -> str:
    if fmt == FORMAT_EMBEDDINGS:
        return "error"
    override = request.headers.get("x-xyberah-block-mode", "").lower()
    return override if override in ("error", "message") else bundle.block_response


def _synthetic_completion(ctx: Ctx, text: str) -> dict[str, Any]:
    now = int(time.time())
    if ctx.fmt == FORMAT_ANTHROPIC:
        return {"id": f"msg_{ctx.request_id}", "type": "message", "role": "assistant", "model": ctx.model,
                "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0}}
    return {"id": f"chatcmpl-{ctx.request_id}", "object": "chat.completion", "created": now, "model": ctx.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "content_filter"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def _synthetic_stream(ctx: Ctx, text: str) -> list[bytes]:
    if ctx.fmt == FORMAT_ANTHROPIC:
        msg = {"id": f"msg_{ctx.request_id}", "type": "message", "role": "assistant", "model": ctx.model,
               "content": [], "stop_reason": None, "stop_sequence": None,
               "usage": {"input_tokens": 0, "output_tokens": 0}}
        return [SSEEvent("message_start", json.dumps({"type": "message_start", "message": msg})).encode(),
                SSEEvent("content_block_start", json.dumps({"type": "content_block_start", "index": 0,
                                                            "content_block": {"type": "text", "text": ""}})).encode(),
                _anthropic_text(0, text),
                SSEEvent("content_block_stop", json.dumps({"type": "content_block_stop", "index": 0})).encode(),
                SSEEvent("message_delta", json.dumps({"type": "message_delta",
                                                      "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                                      "usage": {"output_tokens": 0}})).encode(),
                SSEEvent("message_stop", json.dumps({"type": "message_stop"})).encode()]
    base = {"id": f"chatcmpl-{ctx.request_id}", "object": "chat.completion.chunk", "created": int(time.time()),
            "model": ctx.model}
    return [SSEEvent("", json.dumps({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                                                          "finish_reason": None}]})).encode(),
            _openai_text(base, 0, text),
            SSEEvent("", json.dumps({**base, "choices": [{"index": 0, "delta": {},
                                                          "finish_reason": "content_filter"}]})).encode(),
            SSEEvent("", "[DONE]").encode()]


def _openai_text(template: dict[str, Any], index: int, text: str) -> bytes:
    chunk = {k: v for k, v in template.items() if k not in ("choices", "usage")}
    chunk["choices"] = [{"index": index, "delta": {"content": text}, "logprobs": None, "finish_reason": None}]
    return SSEEvent("", json.dumps(chunk, separators=(",", ":"))).encode()


def _anthropic_text(index: int, text: str) -> bytes:
    return SSEEvent("content_block_delta", json.dumps(
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}},
        separators=(",", ":"))).encode()


def _blocked_response(ctx: Ctx, request: Request, direction: str, dets: list[Detection]) -> Response:
    """403 safety payload, or a synthetic assistant message in ``message`` mode."""
    assert ctx.bundle is not None
    ctx.verdict = "blocked"
    ctx.blocked_direction = direction
    message = ctx.bundle.block_message
    if _block_mode(request, ctx.bundle, ctx.fmt) == "message":
        ctx.status_code = 200
        headers = {"x-xyberah-request-id": ctx.request_id, "x-xyberah-verdict": "blocked"}
        if ctx.stream:
            return StreamingResponse(_iter_bytes(_synthetic_stream(ctx, message)), media_type="text/event-stream",
                                     headers={**headers, "Cache-Control": "no-cache"})
        return JSONResponse(_synthetic_completion(ctx, message), headers=headers)
    return _error(ctx, 403, BLOCK_TYPE, message,
                  {"direction": direction, "violations": _block_details([d for d in dets if d.action == "block"])},
                  headers={"x-xyberah-verdict": "blocked"})


async def _iter_bytes(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for c in chunks:
        yield c


# ---- upstream -------------------------------------------------------------- #
def _upstream(provider: ProviderCfg, fmt: str, request: Request) -> tuple[str, dict[str, str]]:
    base = provider.base_url
    headers = {"content-type": "application/json", "user-agent": f"xyberah-gateway/{VERSION}"}
    if provider.kind == "anthropic":
        url = (base + "/messages") if base.endswith("/v1") else (base + "/v1/messages")
        if provider.api_key:
            headers["x-api-key"] = provider.api_key
        headers["anthropic-version"] = request.headers.get("anthropic-version") or "2023-06-01"
        beta = request.headers.get("anthropic-beta")
        if beta:
            headers["anthropic-beta"] = beta
        return url, headers
    path = "/embeddings" if fmt == FORMAT_EMBEDDINGS else "/chat/completions"
    if provider.kind == "azure_openai":
        url = f"{base}{path}?api-version={provider.api_version or '2024-10-21'}"
        if provider.api_key:
            headers["api-key"] = provider.api_key
        return url, headers
    if provider.api_key:
        headers["authorization"] = f"Bearer {provider.api_key}"
    return base + path, headers


def _sanitize(message: str) -> str:
    """Strip anything secret-shaped from upstream error text before returning it."""
    text = message[:500]
    for m in sorted(find_entities(text, ["API_KEY", "AWS_ACCESS_KEY", "JWT", "HIGH_ENTROPY_SECRET"]),
                    key=lambda m: m.start, reverse=True):
        text = text[:m.start] + "[REDACTED]" + text[m.end:]
    return text


async def _upstream_error(ctx: Ctx, status: int, raw: bytes, retry_after: Optional[str]) -> JSONResponse:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
        err = data.get("error") if isinstance(data, dict) else None
        message = str(err.get("message") if isinstance(err, dict) else (err or data.get("message", "")))
    except (ValueError, AttributeError):
        message = ""
    ctx.verdict = "error"
    ctx.error = f"upstream {status}"
    if status in (401, 403):
        log.error("upstream provider %s rejected the gateway credentials (HTTP %d)",
                  ctx.provider.name if ctx.provider else "?", status)
        return _error(ctx, 502, "upstream_auth_error",
                      "The upstream provider rejected the gateway's credentials. Contact your administrator.")
    if status == 429:
        return _error(ctx, 429, "upstream_rate_limited", "The upstream provider is rate limiting requests.",
                      headers={"retry-after": retry_after} if retry_after else None)
    if 400 <= status < 500:
        return _error(ctx, status, "upstream_invalid_request", _sanitize(message) or "Upstream rejected the request.")
    return _error(ctx, 502, "upstream_error", "The upstream provider returned an error.")


def _cache_key(bundle: Bundle, provider: ProviderCfg, fmt: str, payload: dict[str, Any]) -> str:
    src = json.dumps({"c": bundle.company_id, "u": bundle.consumer_id, "p": bundle.policy_version,
                      "prov": provider.id, "f": fmt, "b": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(src.encode()).hexdigest()


# ---- main handler ---------------------------------------------------------- #
async def _handle(request: Request, fmt: str, route: str) -> Response:
    ctx = Ctx(request_id="xgw" + uuid.uuid4().hex[:21], t0=time.perf_counter(), client_ip=_client_ip(request),
              route=route, fmt=fmt)
    try:
        return await _pipeline(request, ctx)
    except Exception:  # noqa: BLE001 - never leak internals to the client
        log.exception("gateway request %s failed", ctx.request_id)
        ctx.verdict = "error"
        ctx.error = "internal error"
        return _error(ctx, 500, "gateway_error", "The AI gateway encountered an internal error.")
    finally:
        if not ctx.deferred:
            ctx.finish()


async def _pipeline(request: Request, ctx: Ctx) -> Response:
    fmt = ctx.fmt
    key = _consumer_key(request)
    if not key:
        ctx.verdict = "error"
        ctx.error = "missing key"
        return _error(ctx, 401, "authentication_error", "Missing gateway API key (Authorization: Bearer <key>).")
    bundle = await STATE.bundle(key)
    if bundle is None:
        ctx.verdict = "error"
        ctx.error = "invalid key"
        return _error(ctx, 401, "authentication_error", "Invalid gateway API key.")
    ctx.bundle = bundle
    if not bundle.enabled:
        ctx.verdict = "error"
        ctx.error = "consumer disabled"
        return _error(ctx, 403, "permission_error", "This gateway API key is disabled.")

    max_bytes = int(STATE.settings.get("max_body_kb", 2048)) * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        ctx.verdict = "error"
        return _error(ctx, 413, "request_too_large", f"Request body exceeds {max_bytes // 1024} KB.")
    raw = await request.body()
    if len(raw) > max_bytes:
        ctx.verdict = "error"
        return _error(ctx, 413, "request_too_large", f"Request body exceeds {max_bytes // 1024} KB.")
    try:
        payload = json.loads(raw)
    except ValueError:
        ctx.verdict = "error"
        return _error(ctx, 400, "invalid_request_error", "Request body must be valid JSON.")
    if not isinstance(payload, dict):
        ctx.verdict = "error"
        return _error(ctx, 400, "invalid_request_error", "Request body must be a JSON object.")
    original = copy.deepcopy(payload)

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        ctx.verdict = "error"
        return _error(ctx, 400, "invalid_request_error", "The 'model' field is required.")
    ctx.model = model
    ctx.stream = bool(payload.get("stream")) and fmt != FORMAT_EMBEDDINGS
    if bundle.allowed_models and model not in bundle.allowed_models:
        ctx.verdict = "error"
        ctx.error = "model not allowed"
        return _error(ctx, 403, "model_not_allowed", f"Model '{model}' is not allowed for this key.")
    provider = next((p for p in bundle.providers if p.kind in FORMAT_KINDS[fmt]), None)
    if provider is None:
        ctx.verdict = "error"
        ctx.error = "no provider"
        return _error(ctx, 400, "no_provider", "No upstream provider is configured for this API format.")
    ctx.provider = provider
    payload["model"] = provider.model_map.get(model, model)

    rl = await STATE.limiter.hit(f"{bundle.consumer_id}:req", bundle.rpm, 1)
    if not rl.allowed:
        ctx.verdict = "rate_limited"
        retry = str(max(1, int(rl.retry_after + 0.999)))
        return _error(ctx, 429, "rate_limit_exceeded", "Request rate limit exceeded for this key.",
                      {"retry_after_seconds": int(retry)}, headers={"retry-after": retry})

    # Inbound guardrails + DLP
    vault = engine.new_vault()
    slots = request_slots(payload, fmt)
    items = [(s.role, str(get_path(payload, s.path))) for s in slots]
    if items and bundle.rules:
        rows = await STATE.executor.detect(items, bundle.rules, "inbound")
        outcome = engine.transform_batch(items, [engine.from_dicts(r) for r in rows], bundle.rules, vault,
                                         STATE.secret)
        ctx.detections.extend(outcome.detections)
        if outcome.blocked:
            return _blocked_response(ctx, request, "inbound", outcome.detections)
        for slot, new_text, (_, old_text) in zip(slots, outcome.texts, items):
            if new_text != old_text:
                set_path(payload, slot.path, new_text)
    ctx.prompt_tokens = estimate_tokens(sum(len(t) for _, t in items))

    tl = await STATE.limiter.hit(f"{bundle.consumer_id}:tok", bundle.tpm, ctx.prompt_tokens)
    if not tl.allowed:
        ctx.verdict = "rate_limited"
        retry = str(max(1, int(tl.retry_after + 0.999)))
        return _error(ctx, 429, "token_rate_limit_exceeded", "Token rate limit exceeded for this key.",
                      {"retry_after_seconds": int(retry)}, headers={"retry-after": retry})

    cache_key = _cache_key(bundle, provider, fmt, original) if bundle.cache_enabled else ""
    if cache_key:
        cached = await STATE.limiter.cache_get(cache_key)
        if cached is not None:
            ctx.cache_hit = True
            ctx.prompt_tokens, ctx.completion_tokens = 0, 0
            ctx.detections.extend(engine.from_dicts(cached.get("detections", [])))
            headers = {"x-xyberah-request-id": ctx.request_id, "x-xyberah-cache": "hit"}
            if ctx.stream:
                events = [e.encode("utf-8") for e in cached.get("events", [])]
                return StreamingResponse(_iter_bytes(events), media_type="text/event-stream",
                                         headers={**headers, "Cache-Control": "no-cache"})
            return JSONResponse(cached.get("body"), headers=headers)

    url, headers = _upstream(provider, fmt, request)
    client_wants_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
    if ctx.stream and provider.kind == "openai" and fmt == FORMAT_OPENAI:
        payload["stream_options"] = {**(payload.get("stream_options") or {}), "include_usage": True}
    timeout = httpx.Timeout(connect=10.0, read=float(provider.timeout), write=30.0, pool=10.0)

    if ctx.stream:
        return await _stream(request, ctx, url, headers, payload, timeout, vault, cache_key, client_wants_usage)
    return await _non_stream(request, ctx, url, headers, payload, timeout, vault, cache_key)


async def _non_stream(request: Request, ctx: Ctx, url: str, headers: dict[str, str], payload: dict[str, Any],
                      timeout: httpx.Timeout, vault: dict[str, Any], cache_key: str) -> Response:
    assert STATE.client is not None and ctx.bundle is not None
    bundle = ctx.bundle
    t_up = time.perf_counter()
    try:
        resp = await STATE.client.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
        ctx.verdict, ctx.error = "error", "upstream timeout"
        return _error(ctx, 504, "upstream_timeout", "The upstream provider did not respond in time.")
    except httpx.HTTPError as exc:
        ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
        ctx.verdict, ctx.error = "error", f"upstream unreachable: {type(exc).__name__}"
        return _error(ctx, 502, "upstream_unavailable", "The upstream provider is unreachable.")
    ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
    if resp.status_code >= 400:
        return await _upstream_error(ctx, resp.status_code, resp.content, resp.headers.get("retry-after"))
    try:
        data = resp.json()
    except ValueError:
        ctx.verdict, ctx.error = "error", "invalid upstream JSON"
        return _error(ctx, 502, "upstream_error", "The upstream provider returned an invalid response.")
    if not isinstance(data, dict):
        ctx.verdict, ctx.error = "error", "invalid upstream JSON"
        return _error(ctx, 502, "upstream_error", "The upstream provider returned an invalid response.")

    prompt_t, completion_t = usage_from_response(data, ctx.fmt)
    slots = response_slots(data, ctx.fmt)
    items = [(s.role, str(get_path(data, s.path))) for s in slots]
    if prompt_t:
        ctx.prompt_tokens = prompt_t
    ctx.completion_tokens = completion_t or (estimate_tokens(sum(len(t) for _, t in items)) if items else 0)

    out_rules = engine.applicable(bundle.rules, "outbound")
    outbound: list[Detection] = []
    if items and out_rules:
        rows = await STATE.executor.detect(items, out_rules, "outbound")
        outcome = engine.transform_batch(items, [engine.from_dicts(r) for r in rows], out_rules, vault, STATE.secret)
        outbound = outcome.detections
        ctx.detections.extend(outbound)
        if outcome.blocked:
            await STATE.limiter.hit(f"{bundle.consumer_id}:tok", bundle.tpm, ctx.completion_tokens, force=True)
            return _blocked_response(ctx, request, "outbound", outbound)
        new_texts = outcome.texts
    else:
        new_texts = [t for _, t in items]
    for slot, new_text in zip(slots, new_texts):
        final = engine.restore(new_text, vault) if bundle.restore_pseudonyms else new_text
        set_path(data, slot.path, final)

    await STATE.limiter.hit(f"{bundle.consumer_id}:tok", bundle.tpm, ctx.completion_tokens, force=True)
    if cache_key:
        await STATE.limiter.cache_set(cache_key, {"body": data, "detections": [d.to_dict() for d in ctx.detections]},
                                      bundle.cache_ttl)
    return JSONResponse(data, headers={"x-xyberah-request-id": ctx.request_id,
                                       "x-xyberah-cache": "miss" if cache_key else "off"})


async def _stream(request: Request, ctx: Ctx, url: str, headers: dict[str, str], payload: dict[str, Any],
                  timeout: httpx.Timeout, vault: dict[str, Any], cache_key: str,
                  client_wants_usage: bool) -> Response:
    assert STATE.client is not None and ctx.bundle is not None
    bundle = ctx.bundle
    t_up = time.perf_counter()
    req = STATE.client.build_request("POST", url, json=payload,
                                     headers={**headers, "accept": "text/event-stream"}, timeout=timeout)
    try:
        resp = await STATE.client.send(req, stream=True)
    except httpx.TimeoutException:
        ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
        ctx.verdict, ctx.error = "error", "upstream timeout"
        return _error(ctx, 504, "upstream_timeout", "The upstream provider did not respond in time.")
    except httpx.HTTPError as exc:
        ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
        ctx.verdict, ctx.error = "error", f"upstream unreachable: {type(exc).__name__}"
        return _error(ctx, 502, "upstream_unavailable", "The upstream provider is unreachable.")
    if resp.status_code >= 400:
        try:
            raw = await resp.aread()
        finally:
            await resp.aclose()
        ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
        return await _upstream_error(ctx, resp.status_code, raw, resp.headers.get("retry-after"))

    holdback = bundle.stream_holdback or int(STATE.settings.get("stream_holdback", 64))
    guard = StreamGuard(bundle.rules, STATE.executor, vault, STATE.secret, holdback, bundle.restore_pseudonyms)
    block_mode = _block_mode(request, bundle, ctx.fmt)

    async def body() -> AsyncIterator[bytes]:
        parser = SSEParser()
        recorded: list[str] = []
        state: dict[str, Any] = {"template": {"id": f"chatcmpl-{ctx.request_id}", "object": "chat.completion.chunk",
                                              "created": int(time.time()), "model": ctx.model},
                                 "open_blocks": set(), "out_chars": 0, "first": True}
        completed = False
        try:
            async for chunk in resp.aiter_bytes():
                if state["first"]:
                    ctx.upstream_ms = (time.perf_counter() - t_up) * 1000
                    state["first"] = False
                for ev in parser.feed(chunk):
                    for out in await _stream_event(ctx, ev, guard, state, client_wants_usage):
                        if cache_key:
                            recorded.append(out.decode("utf-8"))
                        yield out
            for ev in parser.flush():
                for out in await _stream_event(ctx, ev, guard, state, client_wants_usage):
                    if cache_key:
                        recorded.append(out.decode("utf-8"))
                    yield out
            for idx, text in (await guard.flush_all()).items():
                state["out_chars"] += len(text)
                yield _emit_text(ctx, state, idx, text)
            completed = True
        except StreamBlocked as blocked:
            ctx.detections.extend(blocked.detections)
            ctx.verdict, ctx.blocked_direction = "blocked", "outbound"
            for out in _stream_block(ctx, state, block_mode, blocked.detections):
                yield out
        except httpx.TimeoutException:
            ctx.verdict, ctx.error = "error", "upstream stream timeout"
            yield _stream_error(ctx, "upstream_timeout", "The upstream provider stopped responding.")
        except httpx.HTTPError as exc:
            ctx.verdict, ctx.error = "error", f"upstream stream error: {type(exc).__name__}"
            yield _stream_error(ctx, "upstream_error", "The upstream stream was interrupted.")
        except asyncio.CancelledError:
            ctx.status_code, ctx.verdict, ctx.error = 499, "error", "client disconnected"
            raise
        finally:
            await resp.aclose()
            ctx.detections.extend(guard.detections)
            if not ctx.completion_tokens:
                ctx.completion_tokens = estimate_tokens(state["out_chars"]) if state["out_chars"] else 0
            try:
                await STATE.limiter.hit(f"{bundle.consumer_id}:tok", bundle.tpm, ctx.completion_tokens, force=True)
                if completed and cache_key and ctx.verdict in ("allowed", "masked"):
                    await STATE.limiter.cache_set(
                        cache_key, {"events": recorded, "detections": [d.to_dict() for d in ctx.detections]},
                        bundle.cache_ttl)
            except Exception:  # noqa: BLE001 - bookkeeping must not break the stream teardown
                log.warning("post-stream bookkeeping failed for %s", ctx.request_id, exc_info=True)
            ctx.finish()

    ctx.status_code = 200
    ctx.deferred = True
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"x-xyberah-request-id": ctx.request_id, "Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "x-xyberah-cache": "miss" if cache_key else "off"})


def _emit_text(ctx: Ctx, state: dict[str, Any], index: int, text: str) -> bytes:
    if ctx.fmt == FORMAT_ANTHROPIC:
        return _anthropic_text(index, text)
    return _openai_text(state["template"], index, text)


async def _stream_event(ctx: Ctx, ev: SSEEvent, guard: StreamGuard, state: dict[str, Any],
                        client_wants_usage: bool) -> list[bytes]:
    """Translate one upstream SSE event into zero or more client events."""
    out: list[bytes] = []
    if ctx.fmt == FORMAT_ANTHROPIC:
        data = ev.json()
        if not isinstance(data, dict):
            return [ev.encode()]
        etype = data.get("type", ev.event)
        if etype == "message_start":
            usage = (data.get("message") or {}).get("usage") or {}
            ctx.prompt_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
                + int(usage.get("cache_creation_input_tokens") or 0) or ctx.prompt_tokens
            return [ev.encode()]
        if etype == "content_block_start":
            idx = int(data.get("index", 0))
            block = data.get("content_block") or {}
            if block.get("type") == "text":
                state["open_blocks"].add(idx)
                initial = block.get("text") or ""
                if initial:
                    data["content_block"] = {**block, "text": ""}
                    out.append(SSEEvent(ev.event, json.dumps(data)).encode())
                    released = await guard.feed(idx, initial)
                    if released:
                        state["out_chars"] += len(released)
                        out.append(_anthropic_text(idx, released))
                    return out
            return [ev.encode()]
        if etype == "content_block_delta":
            idx = int(data.get("index", 0))
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                released = await guard.feed(idx, str(delta.get("text") or ""))
                if released:
                    state["out_chars"] += len(released)
                    out.append(_anthropic_text(idx, released))
                return out
            return [ev.encode()]
        if etype == "content_block_stop":
            idx = int(data.get("index", 0))
            released = await guard.flush(idx)
            if released:
                state["out_chars"] += len(released)
                out.append(_anthropic_text(idx, released))
            state["open_blocks"].discard(idx)
            out.append(ev.encode())
            return out
        if etype in ("message_delta", "message_stop"):
            for idx, text in (await guard.flush_all()).items():
                state["out_chars"] += len(text)
                out.append(_anthropic_text(idx, text))
            usage = data.get("usage") or {}
            if usage.get("output_tokens"):
                ctx.completion_tokens = int(usage["output_tokens"])
            out.append(ev.encode())
            return out
        return [ev.encode()]

    # OpenAI chat completion chunks
    if ev.data.strip() == "[DONE]":
        for idx, text in (await guard.flush_all()).items():
            state["out_chars"] += len(text)
            out.append(_openai_text(state["template"], idx, text))
        out.append(SSEEvent("", "[DONE]").encode())
        return out
    data = ev.json()
    if not isinstance(data, dict):
        return [ev.encode()]
    state["template"] = {k: v for k, v in data.items() if k not in ("choices", "usage")} or state["template"]
    usage = data.get("usage")
    if isinstance(usage, dict) and usage:
        ctx.prompt_tokens = int(usage.get("prompt_tokens") or ctx.prompt_tokens)
        ctx.completion_tokens = int(usage.get("completion_tokens") or 0)
    choices = data.get("choices") or []
    if not choices:
        return [ev.encode()] if (client_wants_usage or not usage) else []
    passthrough: list[dict[str, Any]] = []
    for choice in choices:
        idx = int(choice.get("index", 0))
        delta = dict(choice.get("delta") or {})
        content = delta.pop("content", None)
        if isinstance(content, str) and content:
            released = await guard.feed(idx, content)
            if released:
                state["out_chars"] += len(released)
                out.append(_openai_text(state["template"], idx, released))
        if choice.get("finish_reason"):
            released = await guard.flush(idx)
            if released:
                state["out_chars"] += len(released)
                out.append(_openai_text(state["template"], idx, released))
        if delta or choice.get("finish_reason"):
            if content == "" and "role" in delta:
                delta["content"] = ""
            passthrough.append({**choice, "delta": delta})
    if passthrough:
        chunk = {**state["template"], "choices": passthrough}
        if isinstance(usage, dict) and usage and client_wants_usage:
            chunk["usage"] = usage
        out.append(SSEEvent("", json.dumps(chunk, separators=(",", ":"))).encode())
    return out


def _stream_block(ctx: Ctx, state: dict[str, Any], mode: str, dets: list[Detection]) -> list[bytes]:
    """Events that terminate a stream after an outbound block."""
    assert ctx.bundle is not None
    message = ctx.bundle.block_message
    notice = f"\n\n[{message}]"
    if ctx.fmt == FORMAT_ANTHROPIC:
        idx = max(state["open_blocks"]) if state["open_blocks"] else 0
        events = [_anthropic_text(idx, notice)]
        if mode == "message":
            for open_idx in sorted(state["open_blocks"]):
                events.append(SSEEvent("content_block_stop", json.dumps({"type": "content_block_stop",
                                                                         "index": open_idx})).encode())
            events.append(SSEEvent("message_delta", json.dumps({"type": "message_delta",
                                                                "delta": {"stop_reason": "end_turn",
                                                                          "stop_sequence": None},
                                                                "usage": {"output_tokens": 0}})).encode())
            events.append(SSEEvent("message_stop", json.dumps({"type": "message_stop"})).encode())
            return events
        events.append(SSEEvent("error", json.dumps({"type": "error", "error": {
            "type": BLOCK_TYPE, "message": message, "direction": "outbound", "request_id": ctx.request_id,
            "violations": _block_details(dets)}})).encode())
        return events
    tpl = state["template"]
    events = [_openai_text(tpl, 0, notice),
              SSEEvent("", json.dumps({**tpl, "choices": [{"index": 0, "delta": {},
                                                           "finish_reason": "content_filter"}]})).encode()]
    if mode != "message":
        events.append(SSEEvent("", json.dumps({"error": {
            "message": message, "type": BLOCK_TYPE, "code": BLOCK_TYPE, "direction": "outbound",
            "request_id": ctx.request_id, "violations": _block_details(dets)}})).encode())
    events.append(SSEEvent("", "[DONE]").encode())
    return events


def _stream_error(ctx: Ctx, err_type: str, message: str) -> bytes:
    if ctx.fmt == FORMAT_ANTHROPIC:
        return SSEEvent("error", json.dumps({"type": "error", "error": {
            "type": err_type, "message": message, "request_id": ctx.request_id}})).encode()
    return SSEEvent("", json.dumps({"error": {"message": message, "type": err_type, "code": err_type,
                                              "request_id": ctx.request_id}})).encode()


# ---- routes ---------------------------------------------------------------- #
@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """OpenAI-compatible Chat Completions (streaming and non-streaming)."""
    return await _handle(request, FORMAT_OPENAI, "/v1/chat/completions")


@app.post("/v1/messages")
async def messages(request: Request) -> Response:
    """Anthropic-compatible Messages API (streaming and non-streaming)."""
    return await _handle(request, FORMAT_ANTHROPIC, "/v1/messages")


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    """OpenAI-compatible Embeddings (inbound DLP/guardrails only)."""
    return await _handle(request, FORMAT_EMBEDDINGS, "/v1/embeddings")


@app.get("/v1/models")
async def models(request: Request) -> Response:
    """Models this consumer key may call (allow-list, else configured aliases)."""
    ctx = Ctx(request_id="xgw" + uuid.uuid4().hex[:21], t0=time.perf_counter(), client_ip=_client_ip(request),
              route="/v1/models", fmt=FORMAT_OPENAI)
    key = _consumer_key(request)
    bundle = await STATE.bundle(key) if key else None
    if bundle is None or not bundle.enabled:
        return _error(ctx, 401, "authentication_error", "Invalid or missing gateway API key.")
    names = list(bundle.allowed_models)
    if not names:
        for p in bundle.providers:
            names.extend(k for k in p.model_map if k not in names)
    return JSONResponse({"object": "list", "data": [{"id": n, "object": "model", "created": 0,
                                                     "owned_by": "xyberah-gateway"} for n in names]})


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness plus dependency status."""
    redis_up = await STATE.limiter.ping()
    return {"status": "ok", "version": VERSION, "limiter": STATE.limiter.backend, "redis": redis_up,
            "workers": STATE.executor.workers, "audit_dropped": STATE.audit.dropped}


@app.get("/readyz")
async def readyz() -> Response:
    """Readiness: the configuration database must be reachable."""
    def _probe() -> None:
        with db_engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    try:
        await asyncio.to_thread(_probe)
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics (served on the internal port only; not routed publicly)."""
    return PlainTextResponse(STATE.metrics.render(STATE.audit.dropped, STATE.limiter.backend),
                             media_type="text/plain; version=0.0.4")


@app.exception_handler(Exception)
async def _unhandled(_request: Request, _exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
    log.exception("unhandled gateway error")
    return JSONResponse({"error": {"message": "The AI gateway encountered an internal error.",
                                   "type": "gateway_error", "code": "gateway_error"}}, status_code=500)
