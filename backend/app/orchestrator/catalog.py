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


# One-click plugin templates (frameworks / focus areas). Each selects a set of
# Promptfoo plugin ids from the catalog above.
PROMPTFOO_PRESETS: list[dict] = [
    {"id": "owasp-llm", "label": "OWASP LLM Top 10",
     "desc": "Core LLM risks: injection, data disclosure, excessive agency, overreliance, harmful output",
     "plugins": ["indirect-prompt-injection", "hijacking", "system-prompt-override", "ascii-smuggling",
                 "pii", "prompt-extraction", "rag-document-exfiltration", "excessive-agency",
                 "overreliance", "hallucination", "harmful"]},
    {"id": "owasp-api", "label": "OWASP API Top 10",
     "desc": "API-style authorization and injection risks",
     "plugins": ["bola", "rbac", "ssrf", "shell-injection", "sql-injection", "excessive-agency"]},
    {"id": "pii", "label": "PII & Data Leakage",
     "desc": "Sensitive-data disclosure and exfiltration",
     "plugins": ["pii", "prompt-extraction", "cross-session-leak", "rag-document-exfiltration"]},
    {"id": "prompt-injection", "label": "Prompt Injection",
     "desc": "Direct, indirect and encoded injection",
     "plugins": ["indirect-prompt-injection", "hijacking", "system-prompt-override", "ascii-smuggling"]},
    {"id": "harmful", "label": "Harmful Content",
     "desc": "Hate, self-harm, cybercrime, misinformation",
     "plugins": ["harmful", "harmful:hate", "harmful:self-harm", "harmful:cybercrime",
                 "harmful:misinformation-disinformation"]},
    {"id": "security", "label": "Security & Access",
     "desc": "Injection and broken access control",
     "plugins": ["shell-injection", "sql-injection", "ssrf", "rbac", "bola", "excessive-agency"]},
    {"id": "quick", "label": "Quick smoke test",
     "desc": "A fast representative set",
     "plugins": ["harmful", "indirect-prompt-injection", "pii"]},
]

# Map a plugin id to its OWASP LLM Top-10 bucket, for framework-grouped reports.
OWASP_LLM = {
    "LLM01: Prompt Injection": ("indirect-prompt-injection", "hijacking", "system-prompt-override",
                                "ascii-smuggling", "promptinject", "latentinjection", "encoding",
                                "injection", "pliny", "dan", "jailbreak", "tap", "suffix", "crescendo",
                                "pyrit:", "goodside", "grandma", "skeleton"),
    "LLM02: Insecure Output Handling": ("web_injection", "xss", "shell-injection", "sql-injection",
                                        "exploitation", "ssrf"),
    "LLM04: Model Denial of Service": ("reasoning-dos", "divergent-repetition"),
    "LLM06: Sensitive Information Disclosure": ("pii", "prompt-extraction", "cross-session-leak",
                                               "rag-document-exfiltration", "leakreplay", "data-exfil",
                                               "harmful:privacy"),
    "LLM07: Insecure Plugin Design": ("rbac", "bola", "bfla", "debug-access", "tool-discovery"),
    "LLM08: Excessive Agency": ("excessive-agency", "mcp"),
    "LLM09: Overreliance": ("overreliance", "hallucination", "snowball", "misleading", "unverifiable"),
    "LLM10: Model Theft": ("model-identification",),
}


def owasp_bucket(plugin_id: str) -> str:
    pid = plugin_id.lower()
    for bucket, needles in OWASP_LLM.items():
        if any(n in pid for n in needles):
            return bucket
    if "harmful" in pid or "toxic" in pid or "malware" in pid or "lmrc" in pid or "realtoxicity" in pid:
        return "Harmful / Toxic Content"
    return "Other"
