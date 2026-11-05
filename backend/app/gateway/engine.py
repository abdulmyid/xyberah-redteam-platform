"""Policy engine: evaluate guardrail + DLP rules against text and apply transforms.

Detection (CPU-heavy, pure, picklable inputs/outputs) is separated from
transformation (cheap, stateful pseudonym vault) so the gateway can run
detection in a process pool and apply results on the event loop.

Rule shape (plain dict, mirrors the GatewayRule table)::

    {"id": 7, "name": "Mask PII", "kind": "dlp", "direction": "both",
     "action": "mask", "enabled": True, "priority": 100,
     "config": {"entities": ["EMAIL_ADDRESS", "CREDIT_CARD"], "replacement": "[REDACTED_PII]"}}
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Optional

import regex as safe_regex

from .detectors import ALL_ENTITIES, ENTITY_PRIORITY, find_entities
from .injection import analyze as analyze_injection
from .toxicity import TOXICITY_CATEGORIES, analyze_code, analyze_toxicity

CLASSIFIER_KINDS: frozenset[str] = frozenset({"injection", "toxicity", "code"})
SPAN_KINDS: frozenset[str] = frozenset({"dlp", "keywords", "regex"})
RULE_KINDS: tuple[str, ...] = ("injection", "toxicity", "code", "dlp", "keywords", "regex")
DIRECTIONS: tuple[str, ...] = ("inbound", "outbound", "both")
SPAN_ACTIONS: tuple[str, ...] = ("block", "mask", "pseudonymize", "hash", "anonymize", "log")
CLASSIFIER_ACTIONS: tuple[str, ...] = ("block", "log")
TRANSFORM_ACTIONS: frozenset[str] = frozenset({"mask", "pseudonymize", "hash", "anonymize"})
DEFAULT_MASK = "[REDACTED_PII]"
REGEX_TIMEOUT_S = 0.05
MAX_PATTERN_LEN = 512
PSEUDONYM_RE = re.compile(r"<([A-Z][A-Z0-9_]*)_(\d+)>")


class RuleError(ValueError):
    """Raised when a rule definition is invalid."""


@dataclass
class Detection:
    """A single rule hit. ``start``/``end`` are -1 for whole-text classifiers."""

    rule_id: Optional[int]
    rule_name: str
    kind: str
    action: str
    entity: str
    start: int
    end: int
    score: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializable form for API responses and logs."""
        return asdict(self)


# ---- validation ------------------------------------------------------------ #
def validate_rule(kind: str, direction: str, action: str, config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a rule definition; raise :class:`RuleError` if invalid."""
    if kind not in RULE_KINDS:
        raise RuleError(f"kind must be one of {', '.join(RULE_KINDS)}")
    if direction not in DIRECTIONS:
        raise RuleError("direction must be inbound, outbound or both")
    allowed = CLASSIFIER_ACTIONS if kind in CLASSIFIER_KINDS else SPAN_ACTIONS
    if action not in allowed:
        raise RuleError(f"action for {kind} rules must be one of {', '.join(allowed)}")
    cfg = dict(config or {})
    if kind in ("injection", "toxicity"):
        threshold = float(cfg.get("threshold", 0.7 if kind == "injection" else 0.6))
        if not 0.05 <= threshold <= 1.0:
            raise RuleError("threshold must be between 0.05 and 1.0")
        cfg["threshold"] = threshold
    if kind == "injection":
        cfg["semantic"] = bool(cfg.get("semantic", True))
        cfg["scan_system"] = bool(cfg.get("scan_system", False))
    if kind == "toxicity":
        cats = [c for c in cfg.get("categories", TOXICITY_CATEGORIES) if c in TOXICITY_CATEGORIES]
        cfg["categories"] = cats or list(TOXICITY_CATEGORIES)
        cfg["extra_terms"] = [str(t).strip() for t in cfg.get("extra_terms", []) if str(t).strip()][:500]
    if kind == "code":
        mode = cfg.get("mode", "dangerous")
        if mode not in ("dangerous", "any"):
            raise RuleError("code mode must be 'dangerous' or 'any'")
        cfg["mode"] = mode
        cfg["allowed_languages"] = [str(x).strip().lower() for x in cfg.get("allowed_languages", []) if str(x).strip()]
    if kind == "dlp":
        entities = [e for e in cfg.get("entities", []) if e in ALL_ENTITIES]
        if not entities:
            raise RuleError("select at least one DLP entity")
        cfg["entities"] = entities
        cfg["min_score"] = float(cfg.get("min_score", 0.5))
        cfg["entropy_threshold"] = float(cfg.get("entropy_threshold", 4.0))
        cfg["min_length"] = int(cfg.get("min_length", 24))
    if kind == "keywords":
        words = [str(w).strip() for w in cfg.get("keywords", []) if str(w).strip()]
        if not words:
            raise RuleError("add at least one keyword")
        cfg["keywords"] = words[:2000]
        cfg["case_sensitive"] = bool(cfg.get("case_sensitive", False))
        cfg["whole_word"] = bool(cfg.get("whole_word", True))
        cfg["entity"] = _entity_name(cfg.get("entity"), "CUSTOM_KEYWORD")
    if kind == "regex":
        pattern = str(cfg.get("pattern", ""))
        if not pattern or len(pattern) > MAX_PATTERN_LEN:
            raise RuleError(f"pattern is required and must be at most {MAX_PATTERN_LEN} characters")
        try:
            safe_regex.compile(pattern, _regex_flags(bool(cfg.get("ignore_case", True))))
        except safe_regex.error as exc:
            raise RuleError(f"invalid regular expression: {exc}") from exc
        cfg["pattern"] = pattern
        cfg["ignore_case"] = bool(cfg.get("ignore_case", True))
        cfg["entity"] = _entity_name(cfg.get("entity"), "CUSTOM_PATTERN")
    if kind in SPAN_KINDS:
        cfg["replacement"] = str(cfg.get("replacement") or DEFAULT_MASK)[:100]
    return cfg


def _entity_name(value: Any, default: str) -> str:
    name = re.sub(r"[^A-Z0-9_]", "_", str(value or default).upper()).strip("_")
    return name[:40] or default


def _regex_flags(ignore_case: bool) -> int:
    return safe_regex.IGNORECASE if ignore_case else 0


@lru_cache(maxsize=256)
def _keyword_pattern(words: tuple[str, ...], case_sensitive: bool, whole_word: bool) -> re.Pattern[str]:
    alternation = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    body = rf"(?<!\w)(?:{alternation})(?!\w)" if whole_word else f"(?:{alternation})"
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


@lru_cache(maxsize=256)
def _custom_pattern(pattern: str, ignore_case: bool) -> Any:
    return safe_regex.compile(pattern, _regex_flags(ignore_case))


# ---- detection ------------------------------------------------------------- #
def applicable(rules: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    """Enabled rules for ``direction`` ordered by priority (lower runs first)."""
    out = [r for r in rules if r.get("enabled", True) and r.get("direction") in (direction, "both")]
    return sorted(out, key=lambda r: (int(r.get("priority", 100)), r.get("id") or 0))


def detect(text: str, rules: list[dict[str, Any]], direction: str, role: str = "user",
           classifiers: bool = True) -> list[Detection]:
    """Evaluate every applicable rule against ``text``.

    ``classifiers=False`` skips whole-text classifiers (used when scanning a small
    streaming window that is classified separately with more context).
    """
    found: list[Detection] = []
    if not text:
        return found
    for rule in applicable(rules, direction):
        kind = rule.get("kind", "")
        cfg = rule.get("config") or {}
        rid, rname, action = rule.get("id"), rule.get("name") or kind, rule.get("action", "log")
        if kind in CLASSIFIER_KINDS and not classifiers:
            continue
        if kind == "injection":
            if role == "system" and not cfg.get("scan_system", False):
                continue
            res = analyze_injection(text, semantic=bool(cfg.get("semantic", True)))
            if res.score >= float(cfg.get("threshold", 0.7)):
                found.append(Detection(rid, rname, kind, action, "PROMPT_INJECTION", -1, -1, res.score,
                                       "; ".join(res.signals[:4])))
        elif kind == "toxicity":
            res_t = analyze_toxicity(text, cfg.get("categories"), cfg.get("extra_terms"))
            if res_t.score >= float(cfg.get("threshold", 0.6)):
                found.append(Detection(rid, rname, kind, action, "TOXIC_CONTENT", -1, -1, res_t.score,
                                       ", ".join(res_t.signals[:5])))
        elif kind == "code":
            res_c = analyze_code(text, cfg.get("mode", "dangerous"), cfg.get("allowed_languages"))
            if res_c.violation:
                found.append(Detection(rid, rname, kind, action, "CODE_GENERATION", -1, -1, 1.0,
                                       ", ".join(res_c.signals[:4])))
        elif kind == "dlp":
            min_score = float(cfg.get("min_score", 0.5))
            for m in find_entities(text, cfg.get("entities", []), cfg):
                if m.score >= min_score:
                    found.append(Detection(rid, rname, kind, action, m.entity, m.start, m.end, m.score))
        elif kind == "keywords":
            pat = _keyword_pattern(tuple(cfg.get("keywords", [])), bool(cfg.get("case_sensitive")),
                                   bool(cfg.get("whole_word", True)))
            for m in pat.finditer(text):
                found.append(Detection(rid, rname, kind, action, cfg.get("entity", "CUSTOM_KEYWORD"),
                                       m.start(), m.end(), 1.0))
        elif kind == "regex":
            try:
                pat_r = _custom_pattern(cfg.get("pattern", ""), bool(cfg.get("ignore_case", True)))
                for m in pat_r.finditer(text, timeout=REGEX_TIMEOUT_S):
                    if m.end() > m.start():
                        found.append(Detection(rid, rname, kind, action, cfg.get("entity", "CUSTOM_PATTERN"),
                                               m.start(), m.end(), 1.0))
            except TimeoutError:
                found.append(Detection(rid, rname, kind, "log", cfg.get("entity", "CUSTOM_PATTERN"), -1, -1, 0.0,
                                       "pattern evaluation timed out"))
            except safe_regex.error:
                continue
    return found


def detect_many(items: list[tuple[str, str]], rules: list[dict[str, Any]], direction: str,
                classifiers: bool = True) -> list[list[dict[str, Any]]]:
    """Process-pool entry point: detect over many ``(role, text)`` items."""
    return [[d.to_dict() for d in detect(text, rules, direction, role, classifiers)] for role, text in items]


# ---- transformation -------------------------------------------------------- #
def new_vault() -> dict[str, Any]:
    """Per-request pseudonym vault (original <-> token)."""
    return {"forward": {}, "reverse": {}, "counters": {}}


def resolve_spans(dets: list[Detection]) -> list[Detection]:
    """Choose non-overlapping transform spans: earliest start, then strongest entity, then longest."""
    spans = [d for d in dets if d.start >= 0 and d.action in TRANSFORM_ACTIONS]
    spans.sort(key=lambda d: (d.start, ENTITY_PRIORITY.get(d.entity, 50), -(d.end - d.start)))
    chosen: list[Detection] = []
    cursor = -1
    for d in spans:
        if d.start >= cursor:
            chosen.append(d)
            cursor = d.end
        elif d.end > cursor:
            # Partial overlap: widen the chosen span so no fragment of either leaks.
            last = chosen[-1]
            chosen[-1] = Detection(last.rule_id, last.rule_name, last.kind, last.action, last.entity,
                                   last.start, d.end, max(last.score, d.score), last.detail)
            cursor = d.end
    return chosen


def _replacement(d: Detection, original: str, replacement_tpl: str, vault: dict[str, Any], secret: str) -> str:
    if d.action == "mask":
        return replacement_tpl.replace("{entity}", d.entity)
    if d.action == "anonymize":
        return f"<{d.entity}>"
    if d.action == "hash":
        digest = hmac.new(secret.encode(), original.encode(), hashlib.sha256).hexdigest()[:12]
        return f"<{d.entity}:{digest}>"
    # pseudonymize: stable per-request token, reversible via the vault
    forward: dict[str, str] = vault.setdefault("forward", {})
    key = f"{d.entity}\x00{original}"
    if key not in forward:
        counters: dict[str, int] = vault.setdefault("counters", {})
        counters[d.entity] = counters.get(d.entity, 0) + 1
        token = f"<{d.entity}_{counters[d.entity]}>"
        forward[key] = token
        vault.setdefault("reverse", {})[token] = original
    return forward[key]


def apply(text: str, dets: list[Detection], rules: list[dict[str, Any]], vault: dict[str, Any],
          secret: str) -> str:
    """Return ``text`` with transform-action detections replaced."""
    chosen = resolve_spans(dets)
    if not chosen:
        return text
    templates = {r.get("id"): (r.get("config") or {}).get("replacement") or DEFAULT_MASK for r in rules}
    out: list[str] = []
    pos = 0
    for d in chosen:
        out.append(text[pos:d.start])
        out.append(_replacement(d, text[d.start:d.end], templates.get(d.rule_id, DEFAULT_MASK), vault, secret))
        pos = d.end
    out.append(text[pos:])
    return "".join(out)


def restore(text: str, vault: dict[str, Any]) -> str:
    """Replace pseudonym tokens with their originals (response re-identification)."""
    reverse: dict[str, str] = vault.get("reverse") or {}
    if not reverse or "<" not in text:
        return text
    return PSEUDONYM_RE.sub(lambda m: reverse.get(m.group(0), m.group(0)), text)


def from_dicts(rows: list[dict[str, Any]]) -> list[Detection]:
    """Rebuild :class:`Detection` objects from ``detect_many`` output."""
    return [Detection(**row) for row in rows]


@dataclass
class ScanOutcome:
    """Result of scanning a batch of texts."""

    texts: list[str]
    detections: list[Detection]
    blocked: bool


def transform_batch(items: list[tuple[str, str]], detections: list[list[Detection]],
                    rules: list[dict[str, Any]], vault: dict[str, Any], secret: str) -> ScanOutcome:
    """Apply detections to each item; blocked if any detection's action is ``block``."""
    texts: list[str] = []
    flat: list[Detection] = []
    for (_role, text), dets in zip(items, detections):
        flat.extend(dets)
        texts.append(apply(text, dets, rules, vault, secret))
    return ScanOutcome(texts, flat, any(d.action == "block" for d in flat))


def scan(items: list[tuple[str, str]], rules: list[dict[str, Any]], direction: str,
         vault: Optional[dict[str, Any]] = None, secret: str = "") -> ScanOutcome:
    """Synchronous detect + transform (used by the playground and tests)."""
    v = vault if vault is not None else new_vault()
    dets = [from_dicts(rows) for rows in detect_many(items, rules, direction)]
    return transform_batch(items, dets, rules, v, secret)


# ---- verdicts -------------------------------------------------------------- #
def verdicts(dets: list[Detection]) -> tuple[str, str]:
    """(guardrail_verdict, dlp_verdict) summarizing a set of detections."""
    guard = [d for d in dets if d.kind in CLASSIFIER_KINDS]
    dlp = [d for d in dets if d.kind in SPAN_KINDS]
    g = "blocked" if any(d.action == "block" for d in guard) else ("logged" if guard else "pass")
    if any(d.action == "block" for d in dlp):
        v = "blocked"
    elif any(d.action in TRANSFORM_ACTIONS for d in dlp):
        v = "masked"
    elif dlp:
        v = "logged"
    else:
        v = "clean"
    return g, v


# ---- recommended policy ----------------------------------------------------- #
def recommended_rules() -> list[dict[str, Any]]:
    """Rules for a sensible default protection policy."""
    return [
        {"name": "Prompt injection & jailbreak", "kind": "injection", "direction": "inbound", "action": "block",
         "priority": 10, "config": {"threshold": 0.7, "semantic": True, "scan_system": False}},
        {"name": "Secrets & credentials", "kind": "dlp", "direction": "both", "action": "mask", "priority": 20,
         "config": {"entities": ["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "API_KEY", "JWT", "PRIVATE_KEY"],
                    "replacement": "[REDACTED_SECRET]"}},
        {"name": "Payment cards & IBAN", "kind": "dlp", "direction": "both", "action": "mask", "priority": 30,
         "config": {"entities": ["CREDIT_CARD", "IBAN_CODE"], "replacement": DEFAULT_MASK}},
        {"name": "Personal data (PII)", "kind": "dlp", "direction": "inbound", "action": "pseudonymize",
         "priority": 40, "config": {"entities": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "UK_NINO"]}},
        {"name": "Toxic output", "kind": "toxicity", "direction": "outbound", "action": "block", "priority": 50,
         "config": {"threshold": 0.6, "categories": list(TOXICITY_CATEGORIES)}},
        {"name": "Dangerous code in output", "kind": "code", "direction": "outbound", "action": "block",
         "priority": 60, "config": {"mode": "dangerous"}},
    ]
