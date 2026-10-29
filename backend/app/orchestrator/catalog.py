"""What the campaign wizard offers, plus how results map onto report categories."""

# Promptfoo red-team plugins grouped for the UI (ids as accepted by Promptfoo 0.124)
PROMPTFOO_PLUGINS: dict[str, list[dict[str, str]]] = {
    "Prompt injection": [
        {"id": "indirect-prompt-injection", "label": "Indirect prompt injection"},
        {"id": "hijacking", "label": "Goal hijacking"},
        {"id": "system-prompt-override", "label": "System prompt override"},
        {"id": "ascii-smuggling", "label": "ASCII smuggling"},
    ],
    "Data leakage": [
        {"id": "prompt-extraction", "label": "System prompt extraction"},
        {"id": "pii", "label": "PII leakage (all)"},
        {"id": "cross-session-leak", "label": "Cross-session leak"},
        {"id": "rag-document-exfiltration", "label": "RAG document exfiltration"},
    ],
    "Harmful content": [
        {"id": "harmful", "label": "Harmful content (all categories)"},
        {"id": "harmful:hate", "label": "Hate speech"},
        {"id": "harmful:self-harm", "label": "Self-harm"},
        {"id": "harmful:cybercrime", "label": "Cybercrime"},
        {"id": "harmful:misinformation-disinformation", "label": "Misinformation"},
    ],
    "Security & access": [
        {"id": "excessive-agency", "label": "Excessive agency"},
        {"id": "rbac", "label": "Role-based access control"},
        {"id": "bola", "label": "Object-level authorization (BOLA)"},
        {"id": "shell-injection", "label": "Shell injection"},
        {"id": "sql-injection", "label": "SQL injection"},
        {"id": "ssrf", "label": "SSRF"},
    ],
    "Brand & reliability": [
        {"id": "hallucination", "label": "Hallucination"},
        {"id": "overreliance", "label": "Overreliance"},
        {"id": "competitors", "label": "Competitor endorsement"},
        {"id": "politics", "label": "Political statements"},
    ],
}

PROMPTFOO_STRATEGIES = [
    {"id": "basic", "label": "Basic (plugin prompts as generated)"},
    {"id": "jailbreak", "label": "Iterative jailbreak"},
    {"id": "jailbreak:composite", "label": "Composite jailbreaks"},
    {"id": "crescendo", "label": "Crescendo (multi-turn)"},
    {"id": "base64", "label": "Base64 encoding"},
    {"id": "rot13", "label": "ROT13 encoding"},
    {"id": "leetspeak", "label": "Leetspeak"},
    {"id": "multilingual", "label": "Multilingual"},
]

CATEGORIES = ["prompt-injection", "jailbreak", "data-leakage", "harmful-content", "other"]

# Substring rules, checked in order, for plugin/probe/attack ids from all tools
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("data-leakage", ("pii", "prompt-extraction", "leak", "exfil", "cross-session", "replay", "apikey",
                      "sysprompt", "debug-access", "bola", "bfla", "rbac")),
    ("prompt-injection", ("injection", "hijack", "promptinject", "latentinjection", "encoding",
                          "smuggling", "system-prompt-override", "web_injection", "ansiescape")),
    ("jailbreak", ("jailbreak", "dan", "tap", "suffix", "gcg", "grandma", "crescendo", "red_teaming",
                   "tree_of_attacks", "pair", "goodside", "dra", "fitd")),
    ("harmful-content", ("harmful", "toxic", "realtoxicity", "lmrc", "malware", "hate", "self-harm",
                         "misleading", "donotanswer", "cybercrime", "violent", "sexual")),
]


def category_for(plugin_id: str) -> str:
    pid = plugin_id.lower()
    for category, needles in _CATEGORY_RULES:
        if any(n in pid for n in needles):
            return category
    return "other"


SEVERITY_ORDER = ["critical", "high", "medium", "low"]
SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1}
