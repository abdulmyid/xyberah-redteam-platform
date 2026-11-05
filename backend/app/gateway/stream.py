"""Sliding-window guard for streamed model output.

Text deltas are accumulated per output channel (OpenAI choice index / Anthropic
content-block index). Before any text is released to the client, the pending
window is scanned together with a tail of already-released text (for classifier
context). Release then stops short of:

* the last ``holdback`` characters (an entity may still be arriving),
* any detection that ends inside the hold-back region,
* a partially streamed non-whitespace token (secrets are contiguous tokens),
* a partially streamed pseudonym token (``<EMAIL_ADDRESS_1>``) when restoring.

So masking is applied inline before text leaves the gateway, and a ``block``
detection raises :class:`StreamBlocked` before the offending text is released.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import engine
from .engine import Detection
from .executor import DetectionExecutor

TAIL_CHARS = 256
SCAN_STEP = 32
MAX_PENDING = 16_384


class StreamBlocked(Exception):
    """Raised when a block-action rule fires on streamed output."""

    def __init__(self, detections: list[Detection]) -> None:
        super().__init__("stream blocked by policy")
        self.detections = detections


@dataclass
class _Channel:
    pending: str = ""
    tail: str = ""
    released: int = 0


@dataclass
class StreamGuard:
    """Applies outbound rules and pseudonym restoration to streamed text."""

    rules: list[dict[str, Any]]
    executor: DetectionExecutor
    vault: dict[str, Any]
    secret: str
    holdback: int = 64
    restore: bool = True
    channels: dict[int, _Channel] = field(default_factory=dict)
    seen: dict[tuple[Any, str, int], Detection] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rules = engine.applicable(self.rules, "outbound")
        self.holdback = max(16, min(int(self.holdback), 4096))
        self.restore = self.restore and bool(self.vault.get("reverse"))
        self.active = bool(self.rules) or self.restore

    @property
    def detections(self) -> list[Detection]:
        """Distinct detections observed over the whole stream."""
        return list(self.seen.values())

    async def feed(self, index: int, text: str) -> str:
        """Add a delta for ``index``; return the text that is safe to release now."""
        if not self.active:
            return text
        ch = self.channels.setdefault(index, _Channel())
        ch.pending += text
        if len(ch.pending) < self.holdback + SCAN_STEP:
            return ""
        return await self._release(ch, final=False)

    async def flush(self, index: int) -> str:
        """Release everything pending for ``index`` (end of a block/choice)."""
        ch = self.channels.get(index)
        if ch is None or not ch.pending:
            return ""
        return await self._release(ch, final=True)

    async def flush_all(self) -> dict[int, str]:
        """Release every channel's pending text."""
        out: dict[int, str] = {}
        for idx in list(self.channels):
            text = await self.flush(idx)
            if text:
                out[idx] = text
        return out

    async def _release(self, ch: _Channel, final: bool) -> str:
        pending = ch.pending
        dets: list[Detection] = []
        if self.rules:
            ctx = ch.tail + pending
            offset = len(ch.tail)
            rows = await self.executor.detect([("assistant", ctx)], self.rules, "outbound")
            for d in engine.from_dicts(rows[0]):
                if d.start >= 0:
                    if d.start < offset:
                        continue  # belongs to already-released text
                    d.start -= offset
                    d.end -= offset
                dets.append(d)
            for d in dets:
                key = (d.rule_id, d.entity, ch.released + d.start if d.start >= 0 else -1)
                self.seen.setdefault(key, d)
            blocking = [d for d in dets if d.action == "block"]
            if blocking:
                raise StreamBlocked(blocking)

        boundary = len(pending) if final else self._boundary(pending, dets)
        if boundary <= 0:
            return ""
        emit = pending[:boundary]
        spans = [d for d in dets if d.start >= 0 and d.end <= boundary]
        out = engine.apply(emit, spans, self.rules, self.vault, self.secret) if spans else emit
        if self.restore:
            out = engine.restore(out, self.vault)
        ch.pending = pending[boundary:]
        ch.tail = (ch.tail + emit)[-TAIL_CHARS:]
        ch.released += boundary
        return out

    def _boundary(self, pending: str, dets: list[Detection]) -> int:
        boundary = len(pending) - self.holdback
        changed = True
        while changed and boundary > 0:
            changed = False
            for d in dets:
                if d.start >= 0 and d.action in engine.TRANSFORM_ACTIONS and d.start < boundary < d.end:
                    boundary = d.start
                    changed = True
        # Never split a contiguous token (keys, JWTs, card numbers without spaces).
        b = boundary
        while 0 < b < len(pending) and not pending[b - 1].isspace() and not pending[b].isspace():
            b -= 1
        if b > 0 or len(pending) <= MAX_PENDING:
            boundary = b
        # Never split a pseudonym token that may still be arriving.
        if self.restore and boundary > 0:
            lt = pending.rfind("<", max(0, boundary - 48), boundary)
            if lt >= 0 and ">" not in pending[lt:boundary]:
                boundary = lt
        return max(0, boundary)
