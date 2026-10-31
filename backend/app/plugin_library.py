"""Import real attack prompts from the installed scanners into an editable prompt set.

Sources are READ-ONLY: we read garak's probe prompt lists and PyRIT's shipped seed
datasets and copy the prompts out. The original plugins/datasets are never modified;
imported prompts become the user's own editable copy, with source attribution carried
into the set's description.

- PyRIT: YAML seed datasets shipped in the venv (parsed directly here).
- garak: each probe's static `prompts` list (extracted via the garak venv subprocess).
"""
import glob
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import get_settings

MAX_PROMPTS = 2000


# --------------------------------------------------------------------------- #
# PyRIT seed datasets (read the shipped YAML directly)
# --------------------------------------------------------------------------- #
def _pyrit_datasets_dir() -> Path | None:
    tools = get_settings().tools_dir
    for base in glob.glob(str(tools / "pyrit" / "lib" / "python*" / "site-packages" / "pyrit" / "datasets")):
        return Path(base)
    return None


def _pyrit_prompt_files() -> list[Path]:
    d = _pyrit_datasets_dir()
    if not d or not d.exists():
        return []
    files: list[Path] = []
    for pat in ("**/*.prompt", "**/*.yaml", "**/*.yml"):
        files += [p for p in d.glob(pat) if "__pycache__" not in str(p)]
    return sorted(set(files))


def _parse_pyrit_file(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    prompts: list[str] = []
    seeds = data.get("seeds")
    if isinstance(seeds, list):
        for s in seeds:
            if isinstance(s, dict) and s.get("value") and s.get("data_type", "text") == "text":
                prompts.append(str(s["value"]))
            elif isinstance(s, str):
                prompts.append(s)
    elif isinstance(data.get("prompts"), list):
        for s in data["prompts"]:
            if isinstance(s, str):
                prompts.append(s)
            elif isinstance(s, dict) and (s.get("value") or s.get("content")):
                prompts.append(str(s.get("value") or s.get("content")))
    elif isinstance(data.get("value"), str):      # single jailbreak template
        prompts.append(data["value"])
    elif isinstance(data.get("template"), str):
        prompts.append(data["template"])
    if not prompts:
        return None
    return {
        "name": str(data.get("dataset_name") or data.get("name") or path.stem),
        "source": str(data.get("source") or ""),
        "desc": str(data.get("description") or "")[:300],
        "prompts": prompts[:MAX_PROMPTS],
    }


@lru_cache(maxsize=1)
def _pyrit_sources() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in _pyrit_prompt_files():
        parsed = _parse_pyrit_file(f)
        if parsed:
            out["pyrit::" + f.stem] = parsed
    return out


# --------------------------------------------------------------------------- #
# garak probe prompts (extract via the garak venv)
# --------------------------------------------------------------------------- #
_GARAK_SCRIPT = r"""
import importlib, pkgutil, json
import garak.probes
out = {}
for m in pkgutil.iter_modules(garak.probes.__path__):
    if m.name.startswith("_"):
        continue
    try:
        mod = importlib.import_module("garak.probes." + m.name)
    except Exception:
        continue
    for attr in dir(mod):
        cls = getattr(mod, attr)
        pr = getattr(cls, "prompts", None)
        if isinstance(pr, list) and pr:
            vals = [str(x) for x in pr if isinstance(x, str) and x.strip()]
            if vals:
                out[m.name + "." + attr] = vals[:500]
print(json.dumps(out))
"""


@lru_cache(maxsize=1)
def _garak_sources() -> dict[str, dict[str, Any]]:
    py = get_settings().garak_python
    if not py.exists():
        return {}
    try:
        proc = subprocess.run([str(py), "-c", _GARAK_SCRIPT], capture_output=True, text=True, timeout=120)
        data = json.loads(proc.stdout.strip() or "{}")
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for probe_id, prompts in data.items():
        out["garak::" + probe_id] = {
            "name": probe_id, "source": "NVIDIA garak probe",
            "desc": f"garak probe {probe_id}", "prompts": prompts[:MAX_PROMPTS],
        }
    return out


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def list_sources() -> list[dict[str, Any]]:
    from . import datasetpacks
    rows = list(datasetpacks.sources())
    for provider, src in (("pyrit", _pyrit_sources()), ("garak", _garak_sources())):
        for sid, meta in src.items():
            rows.append({"id": sid, "provider": provider, "name": meta["name"],
                         "count": len(meta["prompts"]), "source": meta["source"], "desc": meta["desc"]})
    rows.sort(key=lambda r: (r["provider"], r["name"].lower()))
    return rows


def get_prompts(source_id: str) -> dict[str, Any] | None:
    if source_id.startswith("dataset::"):
        from . import datasetpacks
        pack_id = source_id.split("::", 1)[1]
        p = datasetpacks.PACKS.get(pack_id)
        if not p:
            return None
        prompts = list(datasetpacks.fetch(pack_id))  # may raise on network error
        return {"provider": "dataset", "name": p["name"], "source": p["source"],
                "desc": p["desc"], "prompts": prompts}
    src = _pyrit_sources() if source_id.startswith("pyrit::") else _garak_sources()
    meta = src.get(source_id)
    if not meta:
        return None
    provider = source_id.split("::", 1)[0]
    attribution = meta["source"] or ("NVIDIA garak" if provider == "garak" else "Microsoft PyRIT")
    return {"provider": provider, "name": meta["name"], "source": attribution,
            "desc": meta["desc"], "prompts": meta["prompts"]}
