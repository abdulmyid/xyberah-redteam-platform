"""Run Inspect AI agentic-safety tasks against the target and parse the JSON logs."""
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from ..config import get_settings
from .catalog import category_for
from .targets import Target

INSPECT_TASKS: list[dict[str, str]] = [
    {"id": "tool_use_boundary", "label": "Tool-use boundary", "category": "other"},
    {"id": "prompt_injection_agentic", "label": "Agentic prompt injection", "category": "prompt-injection"},
    {"id": "reasoning_safety", "label": "Reasoning safety", "category": "harmful-content"},
]
VALID_TASKS = {t["id"] for t in INSPECT_TASKS}


def inspect_model_string(target: Target) -> str | None:
    """Map a target to an Inspect provider/model string, or None if unsupported."""
    if target.type == "openai":
        return f"openai/{target.model}"
    if target.type == "anthropic":
        return f"anthropic/{target.model}"
    if target.type == "ollama":
        return f"ollama/{target.model}"
    return None  # custom HTTP targets are not supported by Inspect natively


def run(campaign_id: int, target: Target, tools: dict[str, Any], out: Path,
        stop: threading.Event, stream: Callable) -> list[dict[str, Any]]:
    from .events import bus

    out.mkdir(parents=True, exist_ok=True)
    model = inspect_model_string(target)
    if not model:
        bus.publish(campaign_id, "log", tool="inspect",
                    line="[inspect] custom HTTP targets are not supported; stage skipped")
        return []

    settings = get_settings()
    task_file = settings.engine_dir / "inspect_tasks" / "xyberah_agentic.py"
    chosen = [t for t in tools.get("inspect_tasks", []) if t in VALID_TASKS] or list(VALID_TASKS)
    log_dir = out / "logs"
    findings: list[dict[str, Any]] = []
    env = {**os.environ, "INSPECT_LOG_DIR": str(log_dir)}
    if target.base_url and target.type == "ollama":
        env["OLLAMA_BASE_URL"] = target.base_url

    for task_name in chosen:
        if stop.is_set():
            break
        cmd = [str(settings.inspect_bin), "eval", f"{task_file}@{task_name}",
               "--model", model, "--log-dir", str(log_dir), "--log-format", "json",
               "--display", "plain"]
        stream(campaign_id, "inspect", cmd, cwd=out, env=env, stop=stop)

    for log_file in sorted(log_dir.glob("*.json")):
        findings.extend(_parse_log(log_file))
    return findings


def _parse_log(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    task_name = (data.get("eval", {}) or {}).get("task", "inspect")
    samples = data.get("samples", []) or []
    findings = []
    for sample in samples:
        score_obj = _first_score(sample)
        value = (score_obj or {}).get("value")
        passed = value in ("C", 1, 1.0, True, "CORRECT")
        prompt = _input_text(sample.get("input"))
        output = _output_text(sample)
        findings.append({
            "tool": "inspect",
            "category": category_for(task_name),
            "plugin": f"inspect:{task_name}",
            "severity": "low" if passed else "high",
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "prompt": prompt[:8000],
            "output": output[:8000],
            "reason": "" if passed else str((score_obj or {}).get("explanation", ""))[:4000],
            "extra": {"task": task_name, "raw_score": value},
        })
    return findings


def _first_score(sample: dict[str, Any]) -> dict[str, Any] | None:
    scores = sample.get("scores") or {}
    for v in scores.values():
        if isinstance(v, dict):
            return v
    return None


def _input_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(m.get("content", "") if isinstance(m, dict) else str(m) for m in value)
    return str(value or "")


def _output_text(sample: dict[str, Any]) -> str:
    out = sample.get("output") or {}
    choices = out.get("choices") or []
    if choices:
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
        return str(content)
    return ""
