"""DLP recognizers: PII, financial artifacts and secrets.

Each recognizer is a compiled regex plus an optional validator (Luhn, mod-97, SSN
area rules, entropy, JWT header decode) so matches are precise rather than merely
pattern-shaped. Entity names follow Microsoft Presidio's conventions so policies
read the same way as Presidio analyzer configs.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Optional

# Entity groups shown in the rule builder.
ENTITY_GROUPS: dict[str, list[str]] = {
    "PII": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "UK_NINO", "IP_ADDRESS"],
    "Financial": ["CREDIT_CARD", "IBAN_CODE"],
    "Secrets": ["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "API_KEY", "JWT", "PRIVATE_KEY", "HIGH_ENTROPY_SECRET"],
}
ALL_ENTITIES: list[str] = [e for group in ENTITY_GROUPS.values() for e in group]


@dataclass(frozen=True)
class SpanMatch:
    """A located entity inside a text (character offsets, end exclusive)."""

    entity: str
    start: int
    end: int
    score: float


# ---- validators ------------------------------------------------------------ #
def luhn_valid(digits: str) -> bool:
    """Return True when ``digits`` (only 0-9) passes the Luhn checksum."""
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_CARD_PREFIXES: tuple[tuple[int, int], ...] = (
    (4, 4), (51, 55), (2221, 2720), (34, 34), (37, 37), (6011, 6011), (644, 649),
    (65, 65), (3528, 3589), (300, 305), (36, 36), (38, 39), (62, 62), (5018, 5018),
    (5020, 5020), (5038, 5038), (6304, 6304), (6759, 6759), (6761, 6763), (2200, 2204),
)


def card_prefix_valid(digits: str) -> bool:
    """Return True when ``digits`` starts with a known card-network IIN range."""
    for low, high in _CARD_PREFIXES:
        width = len(str(low))
        if len(digits) >= width and low <= int(digits[:width]) <= high:
            return True
    return False


def iban_valid(raw: str) -> bool:
    """Validate an IBAN with the ISO 13616 mod-97 check."""
    iban = raw.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34 or not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def ssn_valid(area: str, group: str, serial: str) -> bool:
    """Apply SSA structural rules (no 000/666/9xx area, no 00 group, no 0000 serial)."""
    if area in ("000", "666") or area.startswith("9"):
        return False
    if group == "00" or serial == "0000":
        return False
    return len(set(area + group + serial)) > 1


def shannon_entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _b64url_json(segment: str) -> Optional[dict]:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode())
        value = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def jwt_valid(token: str) -> bool:
    """A JWT is three base64url segments whose header decodes to JSON with ``alg``."""
    parts = token.split(".")
    if len(parts) != 3:
        return False
    header = _b64url_json(parts[0])
    return bool(header and "alg" in header)


# ---- recognizers ----------------------------------------------------------- #
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}\b")
_PHONE = re.compile(
    r"(?<![\w+])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]?\d{2,4}){1,3}(?![\w])"
)
_PHONE_CONTEXT = re.compile(r"(?i)\b(?:phone|tel|telephone|mobile|cell|call|whatsapp|fax|contact|sms)\b")
_SSN = re.compile(r"(?<![\d-])(\d{3})([- ]?)(\d{2})\2(\d{4})(?![\d-])")
_SSN_CONTEXT = re.compile(r"(?i)\b(?:ssn|social\s+security|tax\s*id|itin)\b")
_NINO = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6 = re.compile(r"(?<![:\w])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?![:\w])")
_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_AWS_ACCESS = re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA|APKA|ASCA)[A-Z0-9]{16}\b")
_AWS_SECRET = re.compile(
    r"(?i)(?:aws|amazon)[\w\- ]{0,25}?(?:secret|private)?[\w\- ]{0,15}?[\"'`]?\s*[:=]\s*[\"'`]?([A-Za-z0-9/+]{40})(?![A-Za-z0-9/+=])"
)
_API_KEYS = re.compile(
    r"(?<![\w-])(?:"
    r"sk-ant-[A-Za-z0-9_\-]{20,}"
    r"|sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|xox[abposr]-[A-Za-z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{35}"
    r"|glpat-[A-Za-z0-9_\-]{20,}"
    r"|(?:sk|rk)_live_[0-9A-Za-z]{24,}"
    r"|SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}"
    r"|hf_[A-Za-z0-9]{34,}"
    r"|npm_[A-Za-z0-9]{36}"
    r"|xai-[A-Za-z0-9]{40,}"
    r")(?![\w-])"
)
_JWT = re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![\w-])")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----(?:[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|[\s\S]*\Z)"
)
_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_\-])[A-Za-z0-9+/=_\-]{16,}(?![A-Za-z0-9+/=_\-])")


def _iter_email(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _EMAIL.finditer(text):
        yield SpanMatch("EMAIL_ADDRESS", m.start(), m.end(), 0.95)


def _iter_phone(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _PHONE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not 9 <= len(digits) <= 15 or len(set(digits)) == 1:
            continue
        has_format = raw.startswith("+") or "(" in raw or bool(re.search(r"\d[\s.-]\d", raw))
        context = _PHONE_CONTEXT.search(text, max(0, m.start() - 40), m.start()) is not None
        if not (raw.startswith("+") or context or (has_format and len(digits) >= 10)):
            continue
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            continue  # a card number, handled by CREDIT_CARD
        if re.fullmatch(r"\d{4}[-.]\d{2}[-.]\d{2}", raw):
            continue  # ISO date
        yield SpanMatch("PHONE_NUMBER", m.start(), m.end(), 0.75 if context else 0.6)


def _iter_ssn(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _SSN.finditer(text):
        area, sep, group, serial = m.group(1), m.group(2), m.group(3), m.group(4)
        if not ssn_valid(area, group, serial):
            continue
        context = _SSN_CONTEXT.search(text, max(0, m.start() - 40), m.start()) is not None
        if sep == "" and not context:
            continue  # bare 9-digit numbers need context to avoid order IDs etc.
        yield SpanMatch("US_SSN", m.start(), m.end(), 0.9 if context or sep == "-" else 0.6)


def _iter_nino(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _NINO.finditer(text):
        yield SpanMatch("UK_NINO", m.start(), m.end(), 0.85)


def _iter_ip(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _IPV4.finditer(text):
        try:
            ipaddress.IPv4Address(m.group(0))
        except ValueError:
            continue
        yield SpanMatch("IP_ADDRESS", m.start(), m.end(), 0.8)
    for m in _IPV6.finditer(text):
        if m.group(0).count(":") < 2:
            continue
        try:
            ipaddress.IPv6Address(m.group(0))
        except ValueError:
            continue
        yield SpanMatch("IP_ADDRESS", m.start(), m.end(), 0.8)


def _iter_card(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_valid(digits) and card_prefix_valid(digits):
            yield SpanMatch("CREDIT_CARD", m.start(), m.end(), 1.0)


def _iter_iban(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _IBAN.finditer(text):
        if iban_valid(m.group(0)):
            yield SpanMatch("IBAN_CODE", m.start(), m.end(), 1.0)


def _iter_aws_access(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _AWS_ACCESS.finditer(text):
        yield SpanMatch("AWS_ACCESS_KEY", m.start(), m.end(), 1.0)


def _iter_aws_secret(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _AWS_SECRET.finditer(text):
        if shannon_entropy(m.group(1)) >= 3.5:
            yield SpanMatch("AWS_SECRET_KEY", m.start(1), m.end(1), 0.95)


def _iter_api_key(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _API_KEYS.finditer(text):
        yield SpanMatch("API_KEY", m.start(), m.end(), 0.95)


def _iter_jwt(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _JWT.finditer(text):
        if jwt_valid(m.group(0)):
            yield SpanMatch("JWT", m.start(), m.end(), 1.0)


def _iter_private_key(text: str, _cfg: dict) -> Iterable[SpanMatch]:
    for m in _PRIVATE_KEY.finditer(text):
        yield SpanMatch("PRIVATE_KEY", m.start(), m.end(), 1.0)


def _iter_entropy(text: str, cfg: dict) -> Iterable[SpanMatch]:
    threshold = float(cfg.get("entropy_threshold", 4.0))
    min_len = max(16, int(cfg.get("min_length", 24)))
    for m in _TOKEN.finditer(text):
        token = m.group(0)
        if len(token) < min_len:
            continue
        classes = sum(bool(re.search(p, token)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
        if classes < 3 and not (classes >= 2 and re.fullmatch(r"[0-9a-f]+", token) and len(token) >= 32):
            continue
        if shannon_entropy(token) >= threshold:
            yield SpanMatch("HIGH_ENTROPY_SECRET", m.start(), m.end(), 0.7)


RECOGNIZERS: dict[str, Callable[[str, dict], Iterable[SpanMatch]]] = {
    "EMAIL_ADDRESS": _iter_email,
    "PHONE_NUMBER": _iter_phone,
    "US_SSN": _iter_ssn,
    "UK_NINO": _iter_nino,
    "IP_ADDRESS": _iter_ip,
    "CREDIT_CARD": _iter_card,
    "IBAN_CODE": _iter_iban,
    "AWS_ACCESS_KEY": _iter_aws_access,
    "AWS_SECRET_KEY": _iter_aws_secret,
    "API_KEY": _iter_api_key,
    "JWT": _iter_jwt,
    "PRIVATE_KEY": _iter_private_key,
    "HIGH_ENTROPY_SECRET": _iter_entropy,
}

# More specific recognizers win when spans overlap (lower = stronger).
ENTITY_PRIORITY: dict[str, int] = {
    "PRIVATE_KEY": 0, "JWT": 1, "AWS_ACCESS_KEY": 2, "AWS_SECRET_KEY": 3, "API_KEY": 4,
    "CREDIT_CARD": 5, "IBAN_CODE": 6, "US_SSN": 7, "UK_NINO": 8, "EMAIL_ADDRESS": 9,
    "IP_ADDRESS": 10, "PHONE_NUMBER": 11, "HIGH_ENTROPY_SECRET": 12,
}


def find_entities(text: str, entities: Iterable[str], cfg: Optional[dict] = None) -> list[SpanMatch]:
    """Run the selected recognizers over ``text`` and return all raw matches."""
    options = cfg or {}
    found: list[SpanMatch] = []
    for name in entities:
        recognizer = RECOGNIZERS.get(name)
        if recognizer is not None:
            found.extend(recognizer(text, options))
    return found
