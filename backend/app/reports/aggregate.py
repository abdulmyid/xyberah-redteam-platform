"""Scoring and breakdowns computed from a campaign's findings."""
from typing import Any

from ..orchestrator.catalog import SEVERITY_ORDER, SEVERITY_WEIGHT


def summarize(findings: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(findings)
    failed = [f for f in findings if not f["passed"]]
    by_cat: dict[str, dict[str, int]] = {}
    by_sev: dict[str, int] = {s: 0 for s in SEVERITY_ORDER}
    by_tool: dict[str, dict[str, int]] = {}

    for f in findings:
        cat = by_cat.setdefault(f["category"], {"total": 0, "failed": 0})
        cat["total"] += 1
        tool = by_tool.setdefault(f["tool"], {"total": 0, "failed": 0})
        tool["total"] += 1
        if not f["passed"]:
            cat["failed"] += 1
            tool["failed"] += 1
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    # Risk score 0-100: weighted failures against a saturating denominator
    weighted = sum(SEVERITY_WEIGHT.get(f["severity"], 1) for f in failed)
    denom = max(total, 1) * 2  # assume avg weight ~2 if everything failed at low
    risk = min(100, round(100 * weighted / denom)) if total else 0

    return {
        "total": total,
        "failed": len(failed),
        "passed": total - len(failed),
        "pass_rate": round(100 * (total - len(failed)) / total, 1) if total else 100.0,
        "risk_score": risk,
        "risk_band": _band(risk),
        "by_category": by_cat,
        "by_severity": by_sev,
        "by_tool": by_tool,
        "top_failures": _top(failed),
    }


def _band(risk: int) -> str:
    if risk >= 70:
        return "critical"
    if risk >= 40:
        return "high"
    if risk >= 15:
        return "medium"
    return "low"


def _top(failed: list[dict[str, Any]], limit: int = 25) -> list[dict[str, Any]]:
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    ranked = sorted(failed, key=lambda f: (order.get(f["severity"], 9), -(f.get("score") or 0)))
    return ranked[:limit]
