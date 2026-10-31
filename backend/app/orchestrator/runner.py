"""Campaign engine: runs the selected tools as sequential stages.

Each campaign runs in a background thread. A stage is one tool's full run. We
can pause BETWEEN stages (the running stage finishes, then we hold before the
next) and Stop kills the running subprocess immediately. Promptfoo is the
orchestrator for its native checks and for PyRIT (PyRIT runs through a Promptfoo
Python provider); garak and Inspect AI run their own CLIs against the same target.
"""
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session

from ..config import get_settings
from ..db import engine
from ..models import Campaign, Finding
from . import garak_runner, inspect_runner, promptfoo_config, promptfoo_runner
from .catalog import category_for
from .targets import Target, missing_keys, target_env

_procs: dict[int, subprocess.Popen] = {}
_threads: dict[int, threading.Thread] = {}
_stop_flags: dict[int, threading.Event] = {}


def is_running(campaign_id: int) -> bool:
    t = _threads.get(campaign_id)
    return bool(t and t.is_alive())


def request_pause(campaign_id: int) -> None:
    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if c and c.status == "running":
            c.pause_requested = True
            s.add(c)
            s.commit()


def request_resume(campaign_id: int) -> None:
    from .events import bus

    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if not c or c.status != "paused":
            return
        c.pause_requested = False
        c.status = "running"
        s.add(c)
        s.commit()
    bus.publish(campaign_id, "status", status="running")
    _spawn(campaign_id)


def request_stop(campaign_id: int) -> None:
    flag = _stop_flags.get(campaign_id)
    if flag:
        flag.set()
    proc = _procs.get(campaign_id)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_campaign(campaign_id: int) -> None:
    _stop_flags[campaign_id] = threading.Event()
    _spawn(campaign_id)


def _spawn(campaign_id: int) -> None:
    t = threading.Thread(target=_run_campaign, args=(campaign_id,), daemon=True)
    _threads[campaign_id] = t
    t.start()


# --------------------------------------------------------------------------- #
def _run_campaign(campaign_id: int) -> None:
    from .events import bus

    settings = get_settings()
    with Session(engine) as s:
        campaign = s.get(Campaign, campaign_id)
        if not campaign:
            return
        target = Target(**campaign.target)
        tools = campaign.tools
        stages = campaign.stages or _plan_stages(tools)
        campaign.stages = stages
        campaign.status = "running"
        if not campaign.started_at:
            from ..models import utcnow
            campaign.started_at = utcnow()
        s.add(campaign)
        s.commit()

    bus.publish(campaign_id, "status", status="running")
    workdir = settings.campaigns_dir / str(campaign_id)
    workdir.mkdir(parents=True, exist_ok=True)
    stop = _stop_flags.get(campaign_id) or threading.Event()

    for i, stage in enumerate(stages):
        if stop.is_set():
            break
        if stage["status"] in ("done", "failed", "skipped"):
            continue

        # Pause point BETWEEN stages
        if _check_pause(campaign_id):
            return

        _set_stage(campaign_id, i, status="running", started_at=time.time())
        bus.publish(campaign_id, "stage", index=i, tool=stage["tool"], status="running")
        try:
            findings = _run_stage(campaign_id, stage["tool"], target, tools, workdir, stop)
            _save_findings(campaign_id, findings)
            _set_stage(campaign_id, i, status="done", finished_at=time.time(),
                       done=len(findings), total=len(findings))
            bus.publish(campaign_id, "stage", index=i, tool=stage["tool"], status="done",
                        findings=len(findings))
        except Exception as exc:
            _set_stage(campaign_id, i, status="failed", finished_at=time.time(), error=str(exc))
            bus.publish(campaign_id, "stage", index=i, tool=stage["tool"], status="failed", error=str(exc))

    _finalize(campaign_id, stop)


def _run_stage(campaign_id: int, tool: str, target: Target, tools: dict[str, Any],
               workdir: Path, stop: threading.Event) -> list[dict[str, Any]]:
    # Only Promptfoo-driven stages can drive a web chat UI (via the Playwright
    # bridge); garak, PyRIT and Inspect need an HTTP/provider endpoint, so they
    # skip for browser targets. Custom prompts run through Promptfoo eval, so they
    # work against a browser target too.
    if target.type == "browser" and tool not in ("promptfoo", "custom"):
        from .events import bus
        bus.publish(campaign_id, "log", tool=tool,
                    line=f"[{tool}] skipped: not supported for web chat UI (browser) targets")
        return []
    if tool == "promptfoo":
        return _run_promptfoo(campaign_id, target, tools, workdir / "promptfoo", stop)
    if tool == "custom":
        return _run_custom(campaign_id, target, tools, workdir / "custom", stop)
    if tool == "pyrit":
        return _run_pyrit(campaign_id, target, tools, workdir / "pyrit", stop)
    if tool == "garak":
        return _run_garak(campaign_id, target, tools, workdir / "garak", stop)
    if tool == "inspect":
        return inspect_runner.run(campaign_id, target, tools, workdir / "inspect", stop, _stream)
    raise ValueError(f"Unknown tool {tool}")


# ---- Promptfoo (native plugins) ------------------------------------------- #
def _run_promptfoo(campaign_id, target, tools, out: Path, stop) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    # Materialize a saved browser session (authenticated storageState), if any.
    session_path = ""
    if target.type == "browser" and target.browser and target.browser.session_id:
        from . import browser_session
        with Session(engine) as s:
            c = s.get(Campaign, campaign_id)
            company_id = c.company_id if c else None
        session_path = browser_session.materialize(target.browser.session_id, company_id, out) or ""
    cfg = promptfoo_config.build_config(
        campaign_name=f"campaign-{campaign_id}", target=target,
        purpose=tools.get("purpose", ""), plugins=tools.get("promptfoo_plugins", []),
        strategies=tools.get("promptfoo_strategies", ["basic"]),
        num_tests=int(tools.get("num_tests", 5)), workdir=out,
        browser_session_path=session_path,
    )
    results = out / "results.json"
    env = {**os.environ, **target_env(target), "PROMPTFOO_DISABLE_TELEMETRY": "1"}
    cmd = [get_settings().engine_bin, "redteam", "run", "-c", str(cfg),
           "-o", str(results), "--no-progress-bar"]
    _stream(campaign_id, "promptfoo", cmd, cwd=out, env=env, stop=stop)
    return promptfoo_runner.parse_results(results, tool="promptfoo")


def run_single(target: Target, prompt: str, company_id: Optional[int] = None,
               grading: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Send one prompt to a target via a Promptfoo eval and return the output.
    When grading is given, also report pass/fail. Used by retest and the console."""
    import tempfile

    grading = grading or {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        session_path = ""
        if target.type == "browser" and target.browser and target.browser.session_id:
            from . import browser_session
            session_path = browser_session.materialize(target.browser.session_id, company_id, out) or ""
        cfg = promptfoo_config.build_custom_eval_config(
            campaign_name="single", target=target, prompts=[prompt],
            grading=grading, workdir=out, browser_session_path=session_path,
            grade=bool(grading),
        )
        results = out / "results.json"
        env = {**os.environ, **target_env(target), "PROMPTFOO_DISABLE_TELEMETRY": "1"}
        cmd = [get_settings().engine_bin, "eval", "-c", str(cfg), "-o", str(results), "--no-progress-bar"]
        proc = subprocess.run(cmd, cwd=str(out), env=env, capture_output=True, text=True, timeout=300)
        rows = promptfoo_runner.parse_custom(results, severity=grading.get("severity", "high"))
        if not rows:
            return {"ok": False, "error": (proc.stderr or proc.stdout or "no result")[-600:]}
        row = rows[0]
        return {"ok": True, "output": row["output"],
                "passed": row["passed"] if grading else None, "graded": bool(grading)}


def retest_single(campaign_id: int, prompt: str) -> dict[str, Any]:
    """Re-run one finding's prompt against the campaign target (graded when the
    campaign had custom grading). Used by the finding 'retest' action."""
    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if not c:
            return {"ok": False, "error": "campaign gone"}
        target = Target(**c.target)
        grading = (c.tools or {}).get("custom_grading") or {}
        company_id = c.company_id
    return run_single(target, prompt, company_id=company_id, grading=grading)


# ---- Custom prompts (the user's own dataset, via Promptfoo eval) ----------- #
def _run_custom(campaign_id, target, tools, out: Path, stop) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    prompts = [p for p in (tools.get("custom_prompts") or []) if str(p).strip()]
    if not prompts:
        from .events import bus
        bus.publish(campaign_id, "log", tool="custom",
                    line="[custom] no prompts in the selected set; skipping")
        return []
    grading = tools.get("custom_grading") or {}

    # A browser target needs its saved authenticated session materialized first.
    session_path = ""
    if target.type == "browser" and target.browser and target.browser.session_id:
        from . import browser_session
        with Session(engine) as s:
            c = s.get(Campaign, campaign_id)
            company_id = c.company_id if c else None
        session_path = browser_session.materialize(target.browser.session_id, company_id, out) or ""

    cfg = promptfoo_config.build_custom_eval_config(
        campaign_name=f"campaign-{campaign_id}", target=target,
        prompts=prompts, grading=grading, workdir=out,
        browser_session_path=session_path,
    )
    results = out / "results.json"
    env = {**os.environ, **target_env(target), "PROMPTFOO_DISABLE_TELEMETRY": "1"}
    cmd = [get_settings().engine_bin, "eval", "-c", str(cfg), "-o", str(results), "--no-progress-bar"]
    _stream(campaign_id, "custom", cmd, cwd=out, env=env, stop=stop)
    return promptfoo_runner.parse_custom(results, severity=grading.get("severity", "high"))


# ---- PyRIT (via a Promptfoo python provider) ------------------------------ #
def _run_pyrit(campaign_id, target, tools, out: Path, stop) -> list[dict]:
    import yaml

    from .pyrit_attacks import DEFAULT_OBJECTIVES, VALID_ATTACKS

    out.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    objectives = tools.get("pyrit_objectives") or DEFAULT_OBJECTIVES
    attacks = [a for a in tools.get("pyrit_attacks", []) if a in VALID_ATTACKS] or ["red_teaming"]
    provider_src = settings.engine_dir / "providers" / "pyrit_provider.py"

    target_spec = {**target.model_dump(), "grader_model": settings.grader.split(":")[-1],
                   "max_turns": int(tools.get("pyrit_max_turns", 5))}
    targets = [{
        "id": f"file://{provider_src}",
        "label": f"PyRIT {attack}",
        "config": {"pythonExecutable": str(settings.pyrit_python),
                   "target": target_spec, "attack": attack,
                   "max_turns": int(tools.get("pyrit_max_turns", 5))},
    } for attack in attacks]

    config = {
        "description": f"PyRIT attacks for campaign {campaign_id}",
        "providers": targets,
        "prompts": ["{{objective}}"],
        # Pass/fail is derived from PyRIT's own scorer in _parse_pyrit (response.metadata),
        # so no Promptfoo assertion is needed here.
        "tests": [{"vars": {"objective": o}} for o in objectives],
    }
    cfg = out / "pyrit_promptfoo.yaml"
    cfg.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    results = out / "results.json"
    env = {**os.environ, **target_env(target), "PROMPTFOO_DISABLE_TELEMETRY": "1"}
    cmd = [settings.engine_bin, "eval", "-c", str(cfg), "-o", str(results), "--no-progress-bar"]
    _stream(campaign_id, "pyrit", cmd, cwd=out, env=env, stop=stop)
    return _parse_pyrit(results)


def _parse_pyrit(results_json: Path) -> list[dict]:
    import json

    if not results_json.exists():
        return []
    data = json.loads(results_json.read_text(encoding="utf-8"))
    rows = (data.get("results", {}) or {}).get("results", []) or []
    findings = []
    for r in rows:
        meta = (r.get("response", {}) or {}).get("metadata", {}) or {}
        attack = meta.get("attack", "pyrit")
        succeeded = bool(meta.get("attack_succeeded"))
        category = category_for(attack)
        findings.append({
            "tool": "pyrit", "category": category, "plugin": f"pyrit:{attack}",
            "severity": "critical" if succeeded else "low",
            "passed": not succeeded, "score": 0.0 if succeeded else 1.0,
            "prompt": str((r.get("vars", {}) or {}).get("objective", ""))[:8000],
            "output": str((r.get("response", {}) or {}).get("output", ""))[:8000],
            "reason": meta.get("outcome_reason", "") if succeeded else "",
            "extra": {"turns": meta.get("turns"), "outcome": meta.get("outcome")},
        })
    return findings


# ---- garak ----------------------------------------------------------------- #
def _run_garak(campaign_id, target, tools, out: Path, stop) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    python = str(get_settings().garak_python)
    cmd = garak_runner.garak_command(
        python=python, probes=tools.get("garak_probes", []), target=target,
        out_dir=out, generations=int(tools.get("garak_generations", 5)))
    env = {**os.environ, **target_env(target)}
    _stream(campaign_id, "garak", cmd, cwd=out, env=env, stop=stop)
    return garak_runner.parse_report(out / "garak.report.jsonl")


# ---- subprocess streaming -------------------------------------------------- #
def _stream(campaign_id: int, tool: str, cmd: list[str], cwd: Path,
            env: dict[str, str], stop: threading.Event) -> None:
    from .events import bus

    bus.publish(campaign_id, "log", tool=tool, line=f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    _procs[campaign_id] = proc
    assert proc.stdout
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            bus.publish(campaign_id, "log", tool=tool, line=line[:2000])
            prog = promptfoo_runner.progress_from_output(line)
            if prog:
                bus.publish(campaign_id, "progress", tool=tool, done=prog[0], total=prog[1])
        if stop.is_set():
            proc.terminate()
            break
    proc.wait()
    _procs.pop(campaign_id, None)
    if proc.returncode not in (0, None) and not stop.is_set():
        # garak/promptfoo exit non-zero when findings exist; treat output as authoritative
        bus.publish(campaign_id, "log", tool=tool, line=f"[{tool} exited {proc.returncode}]")


# ---- shared state helpers -------------------------------------------------- #
def _plan_stages(tools: dict[str, Any]) -> list[dict[str, Any]]:
    order = ["promptfoo", "custom", "pyrit", "garak", "inspect"]
    return [{"tool": t, "status": "pending", "done": 0, "total": 0,
             "started_at": None, "finished_at": None, "error": ""}
            for t in order if tools.get(t)]


def _set_stage(campaign_id: int, index: int, **fields: Any) -> None:
    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if not c:
            return
        stages = list(c.stages)
        stages[index] = {**stages[index], **fields}
        c.stages = stages
        s.add(c)
        s.commit()


def _check_pause(campaign_id: int) -> bool:
    from .events import bus

    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if c and c.pause_requested:
            c.status = "paused"
            s.add(c)
            s.commit()
            bus.publish(campaign_id, "status", status="paused")
            return True
    return False


def _save_findings(campaign_id: int, findings: list[dict[str, Any]]) -> None:
    if not findings:
        return
    with Session(engine) as s:
        campaign = s.get(Campaign, campaign_id)
        company_id = campaign.company_id if campaign else None
        for f in findings:
            s.add(Finding(campaign_id=campaign_id, company_id=company_id, **f))
        s.commit()


def _finalize(campaign_id: int, stop: threading.Event) -> None:
    from ..models import utcnow
    from .events import bus

    with Session(engine) as s:
        c = s.get(Campaign, campaign_id)
        if not c:
            return
        if c.status == "paused":
            return  # will resume later
        if stop.is_set():
            c.status = "stopped"
        elif any(st["status"] == "failed" for st in c.stages):
            c.status = "completed"  # partial: some stages failed but others produced findings
        else:
            c.status = "completed"
        c.finished_at = utcnow()
        s.add(c)
        s.commit()
        status = c.status
    bus.publish(campaign_id, "status", status=status, final=True)
    if status in ("completed", "stopped"):
        try:
            from ..notify import notify_campaign
            notify_campaign(campaign_id)
        except Exception:
            pass
    _threads.pop(campaign_id, None)
