"""What the campaign wizard offers, plus how results map onto report categories."""

# Promptfoo red-team plugins grouped for the UI (ids as accepted by Promptfoo 0.124)
PROMPTFOO_PLUGINS: dict[str, list[dict[str, str]]] = {
    "Prompt injection & jailbreak": [
        {"id": "indirect-prompt-injection", "label": "Indirect prompt injection"},
        {"id": "hijacking", "label": "Goal hijacking"},
        {"id": "system-prompt-override", "label": "System prompt override"},
        {"id": "ascii-smuggling", "label": "ASCII smuggling"},
        {"id": "special-token-injection", "label": "Special-token injection"},
        {"id": "cca", "label": "Context compliance attack"},
        {"id": "prompt-extraction", "label": "System prompt extraction"},
    ],
    "Jailbreak & safety datasets": [
        {"id": "pliny", "label": "Pliny jailbreaks"},
        {"id": "beavertails", "label": "BeaverTails"},
        {"id": "harmbench", "label": "HarmBench"},
        {"id": "donotanswer", "label": "DoNotAnswer"},
        {"id": "cyberseceval", "label": "CyberSecEval"},
        {"id": "toxic-chat", "label": "ToxicChat"},
        {"id": "xstest", "label": "XSTest"},
        {"id": "aegis", "label": "Aegis"},
        {"id": "unsafebench", "label": "UnsafeBench"},
        {"id": "wordplay", "label": "Wordplay"},
    ],
    "Data & privacy": [
        {"id": "pii", "label": "PII leakage (all)"},
        {"id": "pii:direct", "label": "PII - direct"},
        {"id": "pii:api-db", "label": "PII - API/DB"},
        {"id": "pii:session", "label": "PII - session"},
        {"id": "pii:social", "label": "PII - social engineering"},
        {"id": "cross-session-leak", "label": "Cross-session leak"},
        {"id": "data-exfil", "label": "Data exfiltration"},
        {"id": "rag-document-exfiltration", "label": "RAG document exfiltration"},
        {"id": "rag-source-attribution", "label": "RAG source attribution"},
    ],
    "Security & access control": [
        {"id": "bfla", "label": "Function-level authorization (BFLA)"},
        {"id": "bola", "label": "Object-level authorization (BOLA)"},
        {"id": "rbac", "label": "Role-based access control"},
        {"id": "debug-access", "label": "Debug interface access"},
        {"id": "shell-injection", "label": "Shell injection"},
        {"id": "sql-injection", "label": "SQL injection"},
        {"id": "ssrf", "label": "SSRF"},
        {"id": "tool-discovery", "label": "Tool discovery"},
    ],
    "Agentic & tools": [
        {"id": "excessive-agency", "label": "Excessive agency"},
        {"id": "mcp", "label": "MCP tool exploits"},
        {"id": "model-identification", "label": "Model identification"},
        {"id": "divergent-repetition", "label": "Divergent repetition (DoS)"},
        {"id": "reasoning-dos", "label": "Reasoning DoS"},
        {"id": "goal-misalignment", "label": "Goal misalignment"},
    ],
    "Harmful content": [
        {"id": "harmful", "label": "Harmful content (all categories)"},
        {"id": "harmful:hate", "label": "Hate speech"},
        {"id": "harmful:self-harm", "label": "Self-harm"},
        {"id": "harmful:cybercrime", "label": "Cybercrime"},
        {"id": "harmful:misinformation-disinformation", "label": "Misinformation"},
        {"id": "harmful:violent-crime", "label": "Violent crime"},
        {"id": "harmful:non-violent-crime", "label": "Non-violent crime"},
        {"id": "harmful:sex-crime", "label": "Sex crime"},
        {"id": "harmful:child-exploitation", "label": "Child exploitation"},
        {"id": "harmful:chemical-biological-weapons", "label": "Chem/bio weapons"},
        {"id": "harmful:indiscriminate-weapons", "label": "Indiscriminate weapons"},
        {"id": "harmful:illegal-drugs", "label": "Illegal drugs"},
        {"id": "harmful:privacy", "label": "Privacy violations"},
        {"id": "harmful:intellectual-property", "label": "IP violations"},
        {"id": "harmful:harassment-bullying", "label": "Harassment & bullying"},
        {"id": "harmful:radicalization", "label": "Radicalization"},
        {"id": "harmful:unsafe-practices", "label": "Unsafe practices"},
        {"id": "harmful:graphic-content", "label": "Graphic content"},
        {"id": "harmful:specialized-advice", "label": "Dangerous advice"},
        {"id": "harmful:copyright-violations", "label": "Copyright violations"},
        {"id": "harmful:insults", "label": "Insults"},
        {"id": "harmful:profanity", "label": "Profanity"},
    ],
    "Brand & reliability": [
        {"id": "hallucination", "label": "Hallucination"},
        {"id": "overreliance", "label": "Overreliance"},
        {"id": "unverifiable-claims", "label": "Unverifiable claims"},
        {"id": "competitors", "label": "Competitor endorsement"},
        {"id": "imitation", "label": "Imitation / impersonation"},
        {"id": "politics", "label": "Political statements"},
        {"id": "religion", "label": "Religious bias"},
        {"id": "contracts", "label": "Unauthorized commitments"},
        {"id": "off-topic", "label": "Off-topic / misuse"},
    ],
    "Domain & compliance (collections)": [
        {"id": "medical", "label": "Medical (collection)"},
        {"id": "financial", "label": "Financial (collection)"},
        {"id": "pharmacy", "label": "Pharmacy (collection)"},
        {"id": "insurance", "label": "Insurance (collection)"},
        {"id": "teen-safety", "label": "Teen safety (collection)"},
        {"id": "bias", "label": "Bias (collection)"},
        {"id": "coppa", "label": "COPPA (children's privacy)"},
        {"id": "ferpa", "label": "FERPA (education records)"},
    ],
}

PROMPTFOO_STRATEGIES = [
    {"id": "basic", "label": "Basic (plugin prompts as generated)"},
    {"id": "jailbreak", "label": "Iterative jailbreak"},
    {"id": "jailbreak:tree", "label": "Tree of Attacks (TAP)"},
    {"id": "jailbreak:composite", "label": "Composite jailbreaks"},
    {"id": "jailbreak:likert", "label": "Likert-scale jailbreak"},
    {"id": "jailbreak:meta", "label": "Meta jailbreak"},
    {"id": "jailbreak:hydra", "label": "Hydra multi-turn"},
    {"id": "jailbreak:goblin", "label": "Goblin multi-turn"},
    {"id": "crescendo", "label": "Crescendo (gradual escalation)"},
    {"id": "goat", "label": "GOAT (agentic multi-turn)"},
    {"id": "math-prompt", "label": "Math-prompt obfuscation"},
    {"id": "base64", "label": "Base64 encoding"},
    {"id": "hex", "label": "Hex encoding"},
    {"id": "rot13", "label": "ROT13"},
    {"id": "leetspeak", "label": "Leetspeak"},
    {"id": "homoglyph", "label": "Homoglyph"},
    {"id": "morse", "label": "Morse code"},
    {"id": "piglatin", "label": "Pig Latin"},
    {"id": "camelcase", "label": "camelCase"},
    {"id": "emoji", "label": "Emoji smuggling"},
    {"id": "citation", "label": "Citation framing"},
    {"id": "prompt-injection", "label": "Prompt-injection wrapper"},
    {"id": "best-of-n", "label": "Best-of-N"},
    {"id": "layer", "label": "Layer (chain strategies)"},
    {"id": "retry", "label": "Retry failed"},
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


# Additional framework mappings (plugin id substring -> bucket), for compliance views.
NIST_AI_RMF = {
    "Secure & Resilient": ("injection", "hijack", "jailbreak", "dan", "tap", "suffix", "crescendo",
                           "shell", "sql", "ssrf", "rbac", "bola", "bfla", "ascii-smuggling",
                           "encoding", "promptinject", "skeleton", "pyrit:", "goodside"),
    "Privacy-Enhanced": ("pii", "prompt-extraction", "leak", "exfil", "cross-session", "replay"),
    "Safe": ("harmful", "toxic", "malware", "self-harm", "hate", "violent", "lmrc", "realtoxicity",
             "cybercrime", "weapons"),
    "Valid & Reliable": ("hallucination", "overreliance", "misleading", "snowball", "unverifiable",
                         "packagehallucination"),
    "Fair - Bias Managed": ("bias", "politics", "religion", "imitation", "competitors"),
}

MITRE_ATLAS = {
    "AML.T0051 Prompt Injection": ("injection", "hijack", "promptinject", "latentinjection",
                                   "system-prompt-override", "pliny"),
    "AML.T0054 Jailbreak / Evade": ("jailbreak", "dan", "tap", "suffix", "crescendo", "skeleton",
                                    "grandma", "goodside", "pyrit:"),
    "AML.T0057 Data Exfiltration": ("pii", "leak", "exfil", "prompt-extraction", "cross-session",
                                    "replay", "web_injection"),
    "AML.T0040 ML Attack Staging": ("encoding", "ascii-smuggling", "base64", "rot13", "homoglyph"),
    "AML.T0013 Discovery": ("tool-discovery", "debug-access", "model-identification", "mcp"),
    "AML.T0048 Impact / Harm": ("harmful", "toxic", "malware", "self-harm", "hate", "lmrc", "realtoxicity"),
}

EU_AI_ACT = {
    "Prohibited / Harmful (Art.5)": ("harmful", "toxic", "self-harm", "hate", "violent", "malware",
                                     "cybercrime", "weapons", "lmrc", "realtoxicity"),
    "Transparency (Art.50)": ("hallucination", "overreliance", "imitation", "competitors", "misleading"),
    "Data Governance (Art.10)": ("pii", "leak", "exfil", "prompt-extraction", "cross-session", "replay"),
    "Robustness & Security (Art.15)": ("injection", "hijack", "jailbreak", "dan", "tap", "crescendo",
                                       "shell", "sql", "ssrf", "rbac", "bola", "encoding", "pyrit:"),
    "Non-discrimination (Art.10)": ("bias", "politics", "religion"),
}

FRAMEWORKS = {
    "OWASP LLM Top 10": OWASP_LLM,
    "NIST AI RMF": NIST_AI_RMF,
    "MITRE ATLAS": MITRE_ATLAS,
    "EU AI Act": EU_AI_ACT,
}


# --------------------------------------------------------------------------- #
# DeepTeam engine (confident-ai red-teaming framework). ids are DeepTeam class
# names; labels are human-readable. All validated as no-arg instantiable.
def _lbl(name: str) -> str:
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


_DT_VULNS = [
    "Bias", "Toxicity", "Misinformation", "Hallucination", "PIILeakage", "PromptLeakage",
    "IllegalActivity", "GraphicContent", "PersonalSafety", "ChildProtection", "Ethics",
    "Fairness", "Competition", "IntellectualProperty", "Robustness",
    "ExcessiveAgency", "BOLA", "BFLA", "RBAC", "DebugAccess", "SSRF", "ShellInjection",
    "SQLInjection", "UnexpectedCodeExecution", "SystemReconnaissance", "IndirectInstruction",
    "RecursiveHijacking",
    "GoalTheft", "AgentIdentityAbuse", "AutonomousAgentDrift", "CrossContextRetrieval",
    "ExploitToolAgent", "ExternalSystemAbuse", "InsecureInterAgentCommunication",
    "ToolMetadataPoisoning", "ToolOrchestrationAbuse",
]
_DT_ATTACKS = [
    "PromptInjection", "PromptProbing", "Roleplay", "GrayBox", "InputBypass",
    "AuthorityEscalation", "PermissionEscalation", "GoalRedirection", "ContextPoisoning",
    "ContextFlooding", "EmotionalManipulation", "MathProblem", "Leetspeak", "Multilingual",
]

DEEPTEAM_VULNERABILITIES = [{"id": v, "label": _lbl(v)} for v in _DT_VULNS]
DEEPTEAM_ATTACKS = [{"id": a, "label": _lbl(a)} for a in _DT_ATTACKS]


def _bucket(mapping: dict, plugin_id: str, fallback: str = "Other") -> str:
    pid = plugin_id.lower()
    for bucket, needles in mapping.items():
        if any(n in pid for n in needles):
            return bucket
    if any(h in pid for h in ("harmful", "toxic", "malware", "lmrc", "realtoxicity")):
        return "Harmful / Toxic Content"
    return fallback


def framework_breakdown(plugin_id: str) -> dict:
    """{framework name: bucket} for every supported framework."""
    return {name: _bucket(mapping, plugin_id) for name, mapping in FRAMEWORKS.items()}


# Remediation guidance per OWASP LLM bucket, for the vulnerability report.
REMEDIATION = {
    "LLM01: Prompt Injection": "Separate system and user content; never let untrusted input alter instructions. Use strict input/output validation, instruction-hierarchy prompts, and a guardrail model on inputs and outputs.",
    "LLM02: Insecure Output Handling": "Treat model output as untrusted. Encode/sanitize before rendering (no raw HTML/markdown execution), and never pass output directly to shells, SQL, eval, or network calls without validation.",
    "LLM04: Model Denial of Service": "Enforce input length, output token and request-rate limits; add per-user quotas and timeouts; detect and cut off divergent/looping generations.",
    "LLM06: Sensitive Information Disclosure": "Keep secrets and other users' data out of the context window; apply output PII/secret scrubbing; scope retrieval to the caller; never place secrets in the system prompt.",
    "LLM07: Insecure Plugin Design": "Enforce least privilege and per-tool authorization; validate tool arguments server-side; require explicit allow-lists for tools and resources.",
    "LLM08: Excessive Agency": "Require human approval for state-changing or high-impact actions; constrain tools, scopes and spend; default to read-only.",
    "LLM09: Overreliance": "Add citations and uncertainty signalling; verify facts against trusted sources; label AI output and discourage blind reliance in the UI.",
    "LLM10: Model Theft": "Rate-limit and monitor for extraction patterns; avoid echoing model/config details; apply auth and watermarking where applicable.",
    "Harmful / Toxic Content": "Apply a content-safety classifier on inputs and outputs; refuse disallowed categories; tune the system prompt and add a moderation guardrail.",
    "Other": "Review failed cases individually, add targeted guardrails or prompt constraints, and re-test.",
}


def remediation_for(bucket: str) -> str:
    return REMEDIATION.get(bucket, REMEDIATION["Other"])
