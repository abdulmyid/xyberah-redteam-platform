"""Promptfoo Python provider that runs a PyRIT attack against the real target.

Promptfoo calls `call_api(objective, options, context)` once per objective. We
build the configured PyRIT target + attack, run the (possibly multi-turn) attack,
and return the final model response plus metadata saying whether PyRIT's own
scorer judged the objective achieved. A Promptfoo assertion then passes when the
model resisted (attack did NOT succeed).

Run this with the PyRIT virtualenv's Python via the provider's
`pythonExecutable` config. PyRIT 1.1 API.
"""
import asyncio
import os
from typing import Any

_INITIALIZED = False


async def _ensure_pyrit() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    from pyrit.setup import IN_MEMORY, initialize_pyrit_async

    await initialize_pyrit_async(IN_MEMORY)
    _INITIALIZED = True


def _build_target(spec: dict[str, Any]):
    from pyrit.prompt_target import HTTPTarget, LiteLLMChatTarget, OpenAIChatTarget

    ttype = spec.get("type")
    if ttype == "openai":
        return OpenAIChatTarget(
            model_name=spec["model"],
            endpoint=spec.get("base_url") or None,
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=spec.get("temperature"),
        )
    if ttype == "anthropic":
        return LiteLLMChatTarget(model_name=f"anthropic/{spec['model']}",
                                 api_key=os.getenv("ANTHROPIC_API_KEY"))
    if ttype == "ollama":
        base = spec.get("base_url") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return OpenAIChatTarget(model_name=spec["model"], endpoint=f"{base.rstrip('/')}/v1/chat/completions",
                                api_key="ollama")
    if ttype in ("http", "demo"):
        h = spec["http"]
        return HTTPTarget(http_request=_raw_http(h), prompt_regex_string="{PROMPT}",
                          callback_function=_http_response_parser(h.get("response_path", "reply")))
    raise ValueError(f"Unsupported PyRIT target type: {ttype}")


def _raw_http(h: dict[str, Any]) -> str:
    import json
    from urllib.parse import urlsplit

    u = urlsplit(h["url"])
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    body = json.dumps(h.get("body", {"message": "{PROMPT}"})).replace('"{{prompt}}"', '"{PROMPT}"')
    body = body.replace("{{prompt}}", "{PROMPT}")
    headers = {"Host": u.netloc, "Content-Type": "application/json", **h.get("headers", {})}
    header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    return f"{h.get('method', 'POST')} {path} HTTP/1.1\r\n{header_lines}\r\n\r\n{body}"


def _http_response_parser(path: str):
    import json

    def parse(response) -> str:
        try:
            data = json.loads(response.content)
        except Exception:
            return response.content.decode("utf-8", "replace")
        for part in path.split("."):
            data = data[int(part)] if part.isdigit() else data[part]
        return str(data)

    return parse


def _grader_target(spec: dict[str, Any]):
    """Model PyRIT uses to score and (for multi-turn) play the adversary."""
    from pyrit.prompt_target import OpenAIChatTarget

    grader = spec.get("grader_model", "gpt-4.1-mini")
    return OpenAIChatTarget(model_name=grader, api_key=os.getenv("OPENAI_API_KEY"))


def _build_attack(attack: str, target, spec: dict[str, Any]):
    from pyrit.executor.attack import (AttackAdversarialConfig, AttackScoringConfig,
                                       CrescendoAttack, PAIRAttack, PromptSendingAttack,
                                       RedTeamingAttack, SkeletonKeyAttack, TAPAttack)
    from pyrit.score import SelfAskRefusalScorer

    grader = _grader_target(spec)
    scoring = AttackScoringConfig(objective_scorer=SelfAskRefusalScorer(chat_target=grader))
    adversarial = AttackAdversarialConfig(target=grader)
    max_turns = int(spec.get("max_turns", 5))

    if attack == "prompt_sending":
        return PromptSendingAttack(objective_target=target, attack_scoring_config=scoring)
    if attack == "skeleton_key":
        return SkeletonKeyAttack(objective_target=target, attack_scoring_config=scoring)
    if attack == "red_teaming":
        return RedTeamingAttack(objective_target=target, attack_adversarial_config=adversarial,
                                attack_scoring_config=scoring, max_turns=max_turns)
    if attack == "crescendo":
        return CrescendoAttack(objective_target=target, attack_adversarial_config=adversarial,
                               attack_scoring_config=scoring, max_turns=max_turns)
    if attack == "tap":
        return TAPAttack(objective_target=target, attack_adversarial_config=adversarial,
                         attack_scoring_config=scoring, max_turns=max_turns)
    if attack == "pair":
        return PAIRAttack(objective_target=target, attack_adversarial_config=adversarial,
                          attack_scoring_config=scoring, max_turns=max_turns)
    raise ValueError(f"Unknown PyRIT attack: {attack}")


async def _run(objective: str, config: dict[str, Any]) -> dict[str, Any]:
    from pyrit.models import AttackOutcome

    await _ensure_pyrit()
    target = _build_target(config["target"])
    attack = _build_attack(config.get("attack", "red_teaming"), target, config)
    result = await attack.execute_async(objective=objective)

    succeeded = result.outcome == AttackOutcome.SUCCESS
    response = ""
    if result.last_response is not None:
        response = getattr(result.last_response, "converted_value", None) or str(result.last_response)
    return {
        "output": response,
        "metadata": {
            "attack": config.get("attack", "red_teaming"),
            "attack_succeeded": succeeded,
            "outcome": str(result.outcome.value if hasattr(result.outcome, "value") else result.outcome),
            "outcome_reason": result.outcome_reason or "",
            "turns": result.executed_turns,
            "objective": objective,
        },
    }


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]):
    """Promptfoo entry point. `prompt` is the attack objective."""
    config = (options or {}).get("config", {})
    try:
        return asyncio.run(_run(prompt, config))
    except Exception as exc:  # surface as a provider error, don't crash the run
        return {"error": f"PyRIT attack failed: {type(exc).__name__}: {exc}"}
