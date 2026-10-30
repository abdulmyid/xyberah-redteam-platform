"""Version info and 'update to latest PyPI release' for garak and PyRIT.

Each tool lives in its own virtualenv under $XYBERAH_DATA_DIR/tools so they can
be upgraded at runtime without rebuilding the image and without clashing
dependencies. The image seeds these venvs on first boot (see entrypoint).
"""
import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from ..config import get_settings

PYPI_NAME = {"garak": "garak", "pyrit": "pyrit", "inspect": "inspect-ai", "modelaudit": "modelaudit"}
IMPORT_NAME = {"garak": "garak", "pyrit": "pyrit", "inspect": "inspect_ai", "modelaudit": "modelaudit"}


def _python(tool: str) -> Path:
    s = get_settings()
    return {"garak": s.garak_python, "pyrit": s.pyrit_python, "inspect": s.inspect_python, "modelaudit": s.modelaudit_python}[tool]


def _installed_version(tool: str) -> str | None:
    py = _python(tool)
    if not py.exists():
        return None
    try:
        out = subprocess.run(
            [str(py), "-c", f"import importlib.metadata as m; print(m.version('{IMPORT_NAME[tool]}'))"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _latest_version(tool: str) -> str | None:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{PYPI_NAME[tool]}/json", timeout=10) as r:
            data = json.load(r)
        return data["info"]["version"]
    except Exception:
        return None


def list_tool_versions() -> dict[str, Any]:
    result = {}
    for tool in ("garak", "pyrit", "inspect", "modelaudit"):
        installed = _installed_version(tool)
        latest = _latest_version(tool)
        result[tool] = {
            "installed": installed,
            "latest": latest,
            "update_available": bool(installed and latest and installed != latest),
            "ready": installed is not None,
        }
    return result


def update_tool(tool: str) -> dict[str, Any]:
    """pip-upgrade the tool in its venv to the newest PyPI release."""
    py = _python(tool)
    if not py.exists():
        return {"ok": False, "error": f"{tool} environment not found at {py}"}
    before = _installed_version(tool)
    cmd = [str(py), "-m", "pip", "install", "--upgrade",
           "--extra-index-url", "https://download.pytorch.org/whl/cpu", PYPI_NAME[tool]]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    after = _installed_version(tool)
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "tool": tool,
        "from": before,
        "to": after,
        "changed": before != after,
        "log": (proc.stdout + proc.stderr)[-4000:],
    }
