"""Parse Promptfoo eval output (-o results.json) into Finding dicts."""
import json
from pathlib import Path
from typing import Any

from .catalog import category_for

_SEVERITY_BY_CATEGORY = {
    "prompt-injection": "high", "data-leakage": "high",
    "jailbreak": "high", "harmful-content": "high", "other": "medium",
}


def _plugin_id(result: dict[str, Any]) -> str:
    meta = (result.get("testCase", {}) or {}).get("metadata", {}) or {}
    return meta.get("pluginId") or meta.get("plugin") or result.get("testCase", {}).get("description", "promptfoo")


def _severity(result: dict[str, Any], category: str) -> str:
    meta = (result.get("testCase", {}) or {}).get("metadata", {}) or {}
    sev = (meta.get("severity") or "").lower()
    if sev in ("critical", "high", "medium", "low"):
        return sev
    return _SEVERITY_BY_CATEGORY.get(category, "medium")


def parse_results(results_json: Path, tool: str = "promptfoo") -> list[dict[str, Any]]:
    if not results_json.exists():
        return []
    data = json.loads(results_json.read_text(encoding="utf-8"))
    rows = (data.get("results", {}) or {}).get("results", []) or []
    findings: list[dict[str, Any]] = []
    for r in rows:
        plugin = _plugin_id(r)
        category = category_for(plugin)
        passed = bool(r.get("success"))
        grading = r.get("gradingResult") or {}
        response = r.get("response") or {}
        prompt = r.get("prompt", {})
        prompt_text = prompt.get("raw") if isinstance(prompt, dict) else str(prompt)
        findings.append({
            "tool": tool,
            "category": category,
            "plugin": plugin,
            "severity": _severity(r, category) if not passed else "low",
            "passed": passed,
            "score": r.get("score"),
            "prompt": str(prompt_text or "")[:8000],
            "output": str(response.get("output", ""))[:8000],
            "reason": "" if passed else str(grading.get("reason", ""))[:4000],
            "extra": {
                "strategy": (r.get("testCase", {}).get("metadata", {}) or {}).get("strategyId"),
                "latency_ms": r.get("latencyMs"),
                "cost": r.get("cost"),
                "tokens": ((response.get("tokenUsage") or r.get("tokenUsage") or {}) or {}).get("total"),
            },
        })
    return findings


def parse_custom(results_json: Path, severity: str = "high") -> list[dict[str, Any]]:
    """Parse a custom-prompt eval. A failed test (the response broke a grading rule)
    becomes a finding at the prompt set's chosen severity."""
    if not results_json.exists():
        return []
    data = json.loads(results_json.read_text(encoding="utf-8"))
    rows = (data.get("results", {}) or {}).get("results", []) or []
    sev = severity if severity in ("critical", "high", "medium", "low") else "high"
    findings: list[dict[str, Any]] = []
    for r in rows:
        passed = bool(r.get("success"))
        grading = r.get("gradingResult") or {}
        response = r.get("response") or {}
        vars_ = r.get("vars", {}) or {}
        prompt = r.get("prompt", {})
        prompt_text = vars_.get("prompt") or (prompt.get("raw") if isinstance(prompt, dict) else str(prompt))
        # Which rule(s) failed, for the report
        failed_checks = []
        for cr in (grading.get("componentResults") or []):
            if not cr.get("pass"):
                a = cr.get("assertion") or {}
                failed_checks.append(a.get("type") or cr.get("reason", ""))
        findings.append({
            "tool": "custom",
            "category": "custom-prompts",
            "plugin": "custom:prompt",
            "severity": sev if not passed else "low",
            "passed": passed,
            "score": r.get("score"),
            "prompt": str(prompt_text or "")[:8000],
            "output": str(response.get("output", ""))[:8000],
            "reason": "" if passed else str(grading.get("reason", ""))[:4000],
            "extra": {
                "failed_checks": failed_checks,
                "latency_ms": r.get("latencyMs"),
                "cost": r.get("cost"),
                "tokens": ((response.get("tokenUsage") or r.get("tokenUsage") or {}) or {}).get("total"),
            },
        })
    return findings


def progress_from_output(line: str) -> tuple[int, int] | None:
    """Best-effort '[n/m]' progress parse from Promptfoo stdout lines."""
    import re

    m = re.search(r"\[(\d+)\s*/\s*(\d+)\]", line)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None
