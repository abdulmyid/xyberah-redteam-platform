"""Render a campaign's findings into HTML, PDF, JSON and CSV."""
import base64
import csv
import io
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..branding import Branding, load_branding
from ..config import get_settings
from . import charts
from .aggregate import summarize

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)


def _logo_data_uri(branding: Branding) -> str | None:
    """Inline the light logo so HTML/PDF are self-contained."""
    ref = branding.logo_light
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return ref or None
    path = get_settings().uploads_dir / Path(ref).name
    if not path.exists():
        static = get_settings().static_dir / "branding" / Path(ref).name
        path = static if static.exists() else path
    if not path.exists():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/svg+xml"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def render_html(campaign: Any, findings: list[dict], tools_used: list[str], target_display: str) -> str:
    branding = load_branding(getattr(campaign, "company_id", None))
    s = summarize(findings)
    cat_rows = [(c, v["failed"], v["total"]) for c, v in sorted(s["by_category"].items())]
    tool_rows = [(t, v["failed"], v["total"]) for t, v in sorted(s["by_tool"].items())]
    framework_svgs = {fw: charts.bars([(k, v["failed"], v["total"]) for k, v in buckets.items()])
                      for fw, buckets in (s.get("by_framework") or {}).items() if buckets}
    started = campaign.started_at.strftime("%Y-%m-%d %H:%M UTC") if campaign.started_at else "—"
    return _env.get_template("report.html.j2").render(
        b=branding, campaign=campaign, s=s,
        target_display=target_display, tools_used=tools_used, started=started,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        logo_data=_logo_data_uri(branding),
        donut_svg=charts.donut(s["passed"], s["failed"]),
        severity_svg=charts.severity_bar(s["by_severity"]),
        framework_svgs=framework_svgs,
        category_svg=charts.bars(cat_rows),
        tool_svg=charts.bars(tool_rows),
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML  # imported lazily: heavy, PDF only

    return HTML(string=html).write_pdf()


def render_json(campaign: Any, findings: list[dict], target_display: str) -> bytes:
    payload = {
        "campaign": {"id": campaign.id, "name": campaign.name, "target": target_display,
                     "status": campaign.status,
                     "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
                     "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None},
        "summary": summarize(findings),
        "findings": findings,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode()


def render_csv(findings: list[dict]) -> bytes:
    buf = io.StringIO()
    cols = ["tool", "category", "plugin", "severity", "passed", "score", "reason", "prompt", "output"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for f in findings:
        row = dict(f)
        for k in ("prompt", "output", "reason"):
            row[k] = (row.get(k) or "").replace("\n", " ")[:2000]
        w.writerow(row)
    return buf.getvalue().encode()
