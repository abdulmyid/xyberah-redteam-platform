"""Turn real LLM traffic into replayable test prompts.

Supports:
- OpenTelemetry/OTLP trace JSON using the GenAI semantic conventions (user
  messages from span events and gen_ai.prompt.* attributes).
- JSONL / NDJSON logs (one record per line), incl. OpenAI-style {"messages":[...]}.
- Plain JSON arrays and CSV are handled by the existing dataset parser.
"""
import json
from typing import Any

_PROMPT_KEYS = ("prompt", "text", "input", "query", "question", "user_input", "content")


def _otlp_attr_value(v: dict) -> Any:
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    if "arrayValue" in v:
        return [_otlp_attr_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {m.get("key"): _otlp_attr_value(m.get("value", {})) for m in v["kvlistValue"].get("values", [])}
    return None


def _attrs_to_dict(attrs: list) -> dict[str, Any]:
    out = {}
    for a in attrs or []:
        if isinstance(a, dict) and "key" in a:
            out[a["key"]] = _otlp_attr_value(a.get("value", {}))
    return out


def _user_from_messages(messages: Any) -> list[str]:
    """Pull user-role message content from a chat 'messages' array."""
    out = []
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except Exception:
            return [messages]
    for m in messages if isinstance(messages, list) else []:
        if isinstance(m, dict):
            role = str(m.get("role", "")).lower()
            content = m.get("content")
            if isinstance(content, list):  # content parts
                content = " ".join(str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in content)
            if content and role in ("user", "human", ""):
                out.append(str(content))
        elif isinstance(m, str):
            out.append(m)
    return out


def extract_otlp(data: dict) -> list[str]:
    prompts: list[str] = []
    for rs in data.get("resourceSpans", []) or []:
        for ss in rs.get("scopeSpans", rs.get("instrumentationLibrarySpans", [])) or []:
            for span in ss.get("spans", []) or []:
                attrs = _attrs_to_dict(span.get("attributes", []))
                # gen_ai.prompt as a JSON blob of messages
                if "gen_ai.prompt" in attrs:
                    prompts += _user_from_messages(attrs["gen_ai.prompt"])
                # indexed gen_ai.prompt.<i>.content (+ .role)
                idx: dict[str, dict] = {}
                for k, v in attrs.items():
                    if k.startswith("gen_ai.prompt."):
                        parts = k.split(".")
                        if len(parts) >= 4:
                            idx.setdefault(parts[2], {})[parts[3]] = v
                for slot in idx.values():
                    role = str(slot.get("role", "")).lower()
                    if slot.get("content") and role in ("user", "human", ""):
                        prompts.append(str(slot["content"]))
                # span events: gen_ai.user.message (+ content)
                for ev in span.get("events", []) or []:
                    name = str(ev.get("name", "")).lower()
                    ea = _attrs_to_dict(ev.get("attributes", []))
                    if "user.message" in name or name in ("gen_ai.user.message", "gen_ai.content.prompt"):
                        body = ea.get("content") or ea.get("gen_ai.prompt") or ea.get("body")
                        if body:
                            prompts += _user_from_messages(body) if isinstance(body, (list,)) else [str(body)]
    return prompts


def extract_jsonl(text: str) -> list[str]:
    prompts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            prompts.append(line)
            continue
        prompts += extract_record(obj)
    return prompts


def extract_record(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if not isinstance(obj, dict):
        return []
    if "messages" in obj:
        got = _user_from_messages(obj["messages"])
        if got:
            return got
    for k in _PROMPT_KEYS:
        v = obj.get(k)
        if isinstance(v, dict):
            v = v.get("prompt") or v.get("content") or v.get("text")
        if isinstance(v, str) and v.strip():
            return [v]
    return []


def dedupe(prompts: list[str], limit: int = 5000) -> list[str]:
    seen, out = set(), []
    for p in prompts:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p[:20000])
        if len(out) >= limit:
            break
    return out
