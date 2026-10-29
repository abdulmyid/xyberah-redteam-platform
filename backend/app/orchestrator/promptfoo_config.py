"""Builds a promptfooconfig.yaml for the Promptfoo stage of a campaign."""
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings
from .targets import Target, promptfoo_provider


def build_config(
    campaign_name: str,
    target: Target,
    purpose: str,
    plugins: list[str],
    strategies: list[str],
    num_tests: int,
    workdir: Path,
) -> Path:
    s = get_settings()
    provider = promptfoo_provider(target)
    if target.system_prompt:
        provider.setdefault("config", {})["instructions"] = target.system_prompt

    redteam: dict[str, Any] = {
        "purpose": purpose or f"Target under test: {target.display}",
        "numTests": num_tests,
        "plugins": [{"id": p} for p in plugins] or [{"id": "harmful"}],
        "strategies": strategies or ["basic"],
    }
    config = {
        "description": f"Xyberah campaign: {campaign_name}",
        "targets": [provider],
        "redteam": redteam,
        # Grade locally with a configured model so no hosted service is needed
        "defaultTest": {"options": {"provider": s.grader}},
    }
    path = workdir / "promptfooconfig.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path
