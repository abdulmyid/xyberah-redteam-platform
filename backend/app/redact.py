"""Scrub PII and secrets from finding text before it is stored, when a company
enables redaction. Conservative, regex-based; favours removing obvious secrets
(keys, tokens, card/SSN numbers, emails) over perfect recall."""
import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("[REDACTED_PRIVATE_KEY]", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("[REDACTED_JWT]", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("[REDACTED_AWS_KEY]", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("[REDACTED_API_KEY]", re.compile(r"\b(?:sk|pk|rk|xoxb|xoxp|ghp|gho|ghs|AIza|hf_)[-_A-Za-z0-9]{12,}\b")),
    ("[REDACTED_BEARER]", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}\b")),
    ("[REDACTED_CARD]", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("[REDACTED_SSN]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("[REDACTED_EMAIL]", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("[REDACTED_PHONE]", re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")),
]


def scrub(text: str) -> str:
    if not text:
        return text
    for repl, pat in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def scrub_finding(f: dict) -> dict:
    """Redact the free-text fields of a finding dict in place."""
    for k in ("prompt", "output", "reason"):
        if f.get(k):
            f[k] = scrub(f[k])
    extra = f.get("extra")
    if isinstance(extra, dict):
        for k in ("failed_checks",):
            v = extra.get(k)
            if isinstance(v, list):
                extra[k] = [scrub(str(x)) for x in v]
    return f
