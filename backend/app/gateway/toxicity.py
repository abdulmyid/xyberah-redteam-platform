"""Outbound content analyzers: toxicity and unauthorized code generation.

Toxicity is a weighted lexicon/pattern classifier over normalized text with five
categories (profanity, harassment, threats, self-harm encouragement, hate). Each
hit contributes its weight with noisy-OR combination, so one strong signal or
several weak ones cross the threshold. Rules can add organization-specific terms.

Code detection finds fenced code blocks (optionally allowing listed languages)
and dangerous shell/script payloads whether fenced or not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .injection import deleet, normalize

TOXICITY_CATEGORIES: list[str] = ["profanity", "harassment", "threat", "self_harm", "hate", "sexual"]

_LEXICON: dict[str, list[tuple[re.Pattern[str], float]]] = {
    "profanity": [
        (re.compile(r"\b(?:fuck(?:ing|er|ed|s)?|motherfuck\w*|cunt|c\*nt)\b"), 0.55),
        (re.compile(r"\b(?:shit(?:ty)?|bullshit|bitch(?:es)?|bastard|asshole|dickhead|prick|wanker|twat)\b"), 0.4),
    ],
    "harassment": [
        (re.compile(r"\byou(?:'re|\s+are)\s+(?:an?\s+)?(?:so\s+|such\s+an?\s+)?(?:stupid|idiot|moron|worthless|pathetic|useless|disgusting|loser|imbecile|retard(?:ed)?|dumb|ugly|trash|garbage)\b"), 0.75),
        (re.compile(r"\b(?:shut\s+up|nobody\s+(?:likes|cares\s+about)\s+you|go\s+to\s+hell|piece\s+of\s+(?:shit|garbage|trash))\b"), 0.6),
    ],
    "threat": [
        (re.compile(r"\bi(?:'ll|\s+will|\s+am\s+going\s+to|'m\s+going\s+to|\s+gonna)\s+(?:kill|hurt|murder|shoot|stab|beat|destroy|find)\s+(?:you|your\s+family)\b"), 0.95),
        (re.compile(r"\b(?:you|they|he|she)\s+(?:deserve|should|ought)\s+to\s+(?:die|be\s+killed|be\s+shot|suffer)\b"), 0.9),
        (re.compile(r"\b(?:kill|murder|shoot|bomb|attack)\s+(?:them|everyone|all\s+of\s+them|the\s+(?:school|crowd))\b"), 0.85),
    ],
    "self_harm": [
        (re.compile(r"\b(?:kill|hurt|harm|cut)\s+yourself\b|\bkys\b"), 0.95),
        (re.compile(r"\byou\s+should\s+(?:just\s+)?(?:die|end\s+it|end\s+your\s+life|disappear)\b"), 0.95),
        (re.compile(r"\b(?:best|easiest|painless)\s+way\s+to\s+(?:kill\s+(?:myself|yourself)|commit\s+suicide|end\s+(?:my|your)\s+life)\b"), 0.9),
    ],
    "hate": [
        (re.compile(r"\b(?:are|is)\s+(?:all\s+)?(?:vermin|subhuman|sub-human|parasites|cockroaches|animals|savages|inferior\s+(?:race|people))\b"), 0.85),
        (re.compile(r"\b(?:exterminate|eradicate|wipe\s+out|gas|lynch|deport\s+all)\s+(?:all\s+|the\s+|those\s+)?\w+"), 0.85),
        (re.compile(r"\b(?:white|black|racial)\s+(?:power|supremacy|genocide)\b|\bethnic\s+cleansing\b"), 0.85),
    ],
    "sexual": [
        (re.compile(r"\b(?:porn(?:ography)?|blowjob|handjob|cumshot|gangbang|deepthroat|anal\s+sex|explicit\s+sex)\b"), 0.6),
        (re.compile(r"\b(?:nude|naked)\s+(?:photos?|pics?|images?)\s+of\b"), 0.5),
    ],
}


@dataclass
class ToxicityResult:
    """Outcome of toxicity analysis."""

    score: float
    categories: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)


def analyze_toxicity(text: str, categories: Optional[list[str]] = None,
                     extra_terms: Optional[list[str]] = None) -> ToxicityResult:
    """Score ``text`` for toxic content in the selected categories."""
    if not text or not text.strip():
        return ToxicityResult(0.0)
    norm = normalize(text[:100_000])
    variants = (norm, deleet(norm))
    selected = categories or TOXICITY_CATEGORIES
    per_cat: dict[str, float] = {}
    signals: list[str] = []
    combined = 0.0
    for cat in selected:
        for pattern, weight in _LEXICON.get(cat, []):
            hits = sum(len(pattern.findall(v)) for v in variants[:1]) or (1 if pattern.search(variants[1]) else 0)
            if not hits:
                continue
            # Repeated hits add evidence with diminishing returns.
            effective = 1 - (1 - weight) ** min(hits, 3)
            per_cat[cat] = 1 - (1 - per_cat.get(cat, 0.0)) * (1 - effective)
            combined = 1 - (1 - combined) * (1 - effective)
            signals.append(cat)
    for term in extra_terms or []:
        t = term.strip().lower()
        if t and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", norm):
            per_cat["custom"] = 1.0
            combined = 1.0
            signals.append(f"custom term: {term.strip()}")
    return ToxicityResult(round(min(1.0, combined), 4), {k: round(v, 4) for k, v in per_cat.items()},
                          sorted(set(signals)))


# ---- code generation ------------------------------------------------------- #
_FENCE = re.compile(r"(?:^|\n)[ \t]*(`{3,}|~{3,})[ \t]*([\w+#.\-]*)")
_DANGEROUS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(?:--no-preserve-root\s+)?(?:/|~|\*|\$HOME)(?:\s|$|;)"), "recursive delete"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:sudo\s+)?(?:ba|z|k)?sh\b"), "pipe remote script to shell"),
    (re.compile(r"(?i)\bpowershell(?:\.exe)?\b[^\n]{0,80}\s-(?:e|en|enc|encodedcommand)\s+[A-Za-z0-9+/=]{16,}"), "encoded PowerShell"),
    (re.compile(r"(?i)\b(?:iex|invoke-expression)\b\s*\(?\s*\(?\s*new-object\s+(?:system\.)?net\.webclient"), "PowerShell download cradle"),
    (re.compile(r"\bbash\s+-i\s+>&\s*/dev/tcp/|\bnc(?:at)?\s+(?:-[a-z]*e[a-z]*\s+/bin/(?:ba)?sh|[^\n]{0,60}\s-e\s+/bin/(?:ba)?sh)"), "reverse shell"),
    (re.compile(r"\bmkfs(?:\.\w+)?\s+/dev/|\bdd\s+if=/dev/(?:zero|random|urandom)\s+of=/dev/[sh]d"), "disk wipe"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/(?:\s|$)"), "world-writable root"),
    (re.compile(r"\beval\s*\(\s*(?:base64_decode|atob|gzinflate)\s*\("), "obfuscated eval"),
    (re.compile(r"(?i)\breg(?:\.exe)?\s+add\s+hklm\\software\\microsoft\\windows\\currentversion\\run\b"), "persistence via Run key"),
    (re.compile(r"(?i)\bvssadmin(?:\.exe)?\s+delete\s+shadows\b"), "shadow-copy deletion"),
]


@dataclass
class CodeResult:
    """Outcome of code-block analysis."""

    violation: bool
    signals: list[str] = field(default_factory=list)


def analyze_code(text: str, mode: str = "dangerous", allowed_languages: Optional[list[str]] = None) -> CodeResult:
    """Detect code generation.

    mode ``dangerous`` flags only destructive/offensive payloads; mode ``any`` also
    flags any fenced code block whose language is not in ``allowed_languages``.
    """
    signals: list[str] = []
    for pattern, label in _DANGEROUS:
        if pattern.search(text):
            signals.append(f"dangerous: {label}")
    if mode == "any":
        allowed = {lang.strip().lower() for lang in (allowed_languages or []) if lang.strip()}
        opening = True  # fences alternate open/close; only opening fences carry a language
        for m in _FENCE.finditer(text):
            is_opening, opening = opening, not opening
            if not is_opening:
                continue
            lang = (m.group(2) or "").lower()
            if lang and lang in allowed:
                continue
            signals.append(f"code block{f' ({lang})' if lang else ''}")
            break
    return CodeResult(bool(signals), signals)
