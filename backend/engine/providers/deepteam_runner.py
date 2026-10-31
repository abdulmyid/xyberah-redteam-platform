"""DeepTeam bridge — runs in the deepteam venv. Reads a JSON config, red-teams the
target (an HTTP/demo endpoint) with the selected vulnerabilities + attacks, and
writes the test cases to an output file for the backend to parse.

Usage: python deepteam_runner.py <config.json> <out.json>
config: {"target": {"url","method","headers","body","response_path"},
         "vulnerabilities": [...], "attacks": [...],
         "attacks_per_vuln": N, "purpose": "..."}
The simulator/evaluation models default to DeepTeam's (OpenAI; needs OPENAI_API_KEY).
"""
import json
import sys
import urllib.request


def _extract(obj, path):
    cur = obj
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _fill(x, prompt):
    if isinstance(x, str):
        return x.replace("{{prompt}}", prompt)
    if isinstance(x, dict):
        return {k: _fill(v, prompt) for k, v in x.items()}
    if isinstance(x, list):
        return [_fill(v, prompt) for v in x]
    return x


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    out_path = sys.argv[2]
    t = cfg["target"]

    def call_target(prompt: str) -> str:
        data = json.dumps(_fill(t["body"], prompt)).encode()
        req = urllib.request.Request(
            t["url"], data=data, method=t.get("method", "POST"),
            headers={"Content-Type": "application/json", **t.get("headers", {})})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            body = json.loads(r.read().decode())
        val = _extract(body, t.get("response_path", "reply"))
        return str(val) if val is not None else ""

    from deepteam import red_team
    from deepteam.test_case.test_case import RTTurn
    import deepteam.vulnerabilities as V
    import deepteam.attacks.single_turn as A

    def model_callback(input, turns=None):
        try:
            reply = call_target(input)
        except Exception as e:  # noqa: BLE001
            reply = f"[target error: {e}]"
        return RTTurn(role="assistant", content=reply)

    def build(names, module, default):
        out = []
        for name in names or []:
            cls = getattr(module, name, None)
            if cls:
                try:
                    out.append(cls())
                except Exception:
                    pass
        if not out and default:
            out.append(getattr(module, default)())
        return out

    vulns = build(cfg.get("vulnerabilities"), V, "Bias")
    attacks = build(cfg.get("attacks"), A, "PromptInjection")

    try:
        risk = red_team(
            model_callback=model_callback, vulnerabilities=vulns, attacks=attacks,
            attacks_per_vulnerability_type=int(cfg.get("attacks_per_vuln", 2)),
            ignore_errors=True, target_purpose=cfg.get("purpose", "") or None,
        )
    except Exception as e:  # noqa: BLE001
        json.dump({"error": str(e)[:600]}, open(out_path, "w"))
        return

    cases = []
    for tc in getattr(risk, "test_cases", []) or []:
        cases.append({
            "input": getattr(tc, "input", "") or "",
            "actual_output": getattr(tc, "actual_output", "") or "",
            "vulnerability": str(getattr(tc, "vulnerability", "") or ""),
            "vulnerability_type": str(getattr(tc, "vulnerability_type", "") or ""),
            "attack_method": str(getattr(tc, "attack_method", "") or ""),
            "score": getattr(tc, "score", None),
            "reason": getattr(tc, "reason", "") or "",
            "error": getattr(tc, "error", None),
            "cvss": getattr(tc, "cvss_score", None),
            "sim_cost": getattr(tc, "simulation_cost", None),
            "eval_cost": getattr(tc, "evaluation_cost", None),
        })
    json.dump({"test_cases": cases}, open(out_path, "w"))


if __name__ == "__main__":
    main()
