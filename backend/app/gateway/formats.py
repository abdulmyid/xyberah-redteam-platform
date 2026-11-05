"""Provider payload adapters (OpenAI Chat Completions, Anthropic Messages, OpenAI
Embeddings) and a Server-Sent Events parser.

Text inside a payload is addressed by *paths* (tuples of keys/indexes) so the
guardrail pipeline can scan every text field and write transformed text back
without understanding each schema.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Union

PathKey = Union[str, int]
Path = tuple[PathKey, ...]

FORMAT_OPENAI = "openai"
FORMAT_ANTHROPIC = "anthropic"
FORMAT_EMBEDDINGS = "embeddings"


@dataclass(frozen=True)
class Slot:
    """A text field inside a payload and the conversational role it belongs to."""

    path: Path
    role: str


def get_path(obj: Any, path: Path) -> Any:
    """Follow ``path`` into nested dicts/lists."""
    cur = obj
    for key in path:
        cur = cur[key]
    return cur


def set_path(obj: Any, path: Path, value: Any) -> None:
    """Assign ``value`` at ``path`` inside nested dicts/lists."""
    cur = obj
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value


def _content_slots(content: Any, base: Path, role: str) -> Iterator[Slot]:
    if isinstance(content, str):
        yield Slot(base, role)
    elif isinstance(content, list):
        for i, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype in ("text", "input_text", "output_text") and isinstance(part.get("text"), str):
                yield Slot(base + (i, "text"), role)
            elif ptype == "tool_result":
                # Tool output is the classic indirect-injection vector: scan it as "tool".
                yield from _content_slots(part.get("content"), base + (i, "content"), "tool")


def request_slots(payload: dict[str, Any], fmt: str) -> list[Slot]:
    """Every scannable text field in a request body."""
    slots: list[Slot] = []
    if fmt == FORMAT_EMBEDDINGS:
        inp = payload.get("input")
        if isinstance(inp, str):
            slots.append(Slot(("input",), "user"))
        elif isinstance(inp, list):
            slots.extend(Slot(("input", i), "user") for i, v in enumerate(inp) if isinstance(v, str))
        return slots
    if fmt == FORMAT_ANTHROPIC:
        system = payload.get("system")
        if system is not None:
            slots.extend(_content_slots(system, ("system",), "system"))
    for i, msg in enumerate(payload.get("messages") or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        if role == "developer":
            role = "system"
        slots.extend(_content_slots(msg.get("content"), ("messages", i, "content"), role))
    return slots


def response_slots(payload: dict[str, Any], fmt: str) -> list[Slot]:
    """Every assistant text field in a non-streaming response body."""
    slots: list[Slot] = []
    if fmt == FORMAT_OPENAI:
        for i, choice in enumerate(payload.get("choices") or []):
            msg = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(msg, dict):
                slots.extend(_content_slots(msg.get("content"), ("choices", i, "message", "content"), "assistant"))
    elif fmt == FORMAT_ANTHROPIC:
        for i, block in enumerate(payload.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                slots.append(Slot(("content", i, "text"), "assistant"))
    return slots


def usage_from_response(payload: dict[str, Any], fmt: str) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) reported by the provider, or zeros."""
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0
    if fmt == FORMAT_ANTHROPIC:
        prompt = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
            + int(usage.get("cache_creation_input_tokens") or 0)
        return prompt, int(usage.get("output_tokens") or 0)
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def estimate_tokens(text_len: int) -> int:
    """Rough token estimate (~4 characters per token) when usage is unavailable."""
    return max(1, (text_len + 3) // 4)


@dataclass
class SSEEvent:
    """One Server-Sent Event."""

    event: str
    data: str

    def encode(self) -> bytes:
        """Wire representation (``event:`` line only when named)."""
        head = f"event: {self.event}\n" if self.event else ""
        body = "".join(f"data: {line}\n" for line in self.data.split("\n"))
        return (head + body + "\n").encode("utf-8")

    def json(self) -> Any:
        """Parse ``data`` as JSON (None for ``[DONE]`` or invalid JSON)."""
        if not self.data or self.data.strip() == "[DONE]":
            return None
        try:
            return json.loads(self.data)
        except ValueError:
            return None


class SSEParser:
    """Incremental SSE parser tolerant of arbitrary chunk boundaries and CRLF."""

    def __init__(self) -> None:
        self._buf = ""
        self._event = ""
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """Consume bytes and return the events completed so far."""
        self._buf += chunk.decode("utf-8", errors="replace")
        events: list[SSEEvent] = []
        while True:
            idx = self._buf.find("\n")
            if idx < 0:
                break
            line = self._buf[:idx].rstrip("\r")
            self._buf = self._buf[idx + 1:]
            if line == "":
                if self._data or self._event:
                    events.append(SSEEvent(self._event, "\n".join(self._data)))
                self._event, self._data = "", []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                self._event = value
            elif field == "data":
                self._data.append(value)
        return events

    def flush(self) -> list[SSEEvent]:
        """Emit any trailing event not terminated by a blank line."""
        tail = self.feed(b"\n\n") if (self._buf or self._data) else []
        return tail
