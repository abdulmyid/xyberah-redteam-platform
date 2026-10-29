"""Tiny dependency-free SVG charts, so the same markup renders in the browser
and in WeasyPrint's PDF engine (no JS, no canvas)."""
from typing import Any


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def donut(passed: int, failed: int, size: int = 160) -> str:
    total = passed + failed
    r, cx, cy = size / 2 - 14, size / 2, size / 2
    circ = 2 * 3.14159265 * r
    fail_frac = (failed / total) if total else 0
    fail_len = circ * fail_frac
    return f"""<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img">
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--ok)" stroke-width="18"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--danger)" stroke-width="18"
    stroke-dasharray="{fail_len:.2f} {circ - fail_len:.2f}" stroke-dashoffset="{circ/4:.2f}"
    transform="rotate(-90 {cx} {cy})"/>
  <text x="{cx}" y="{cy-2}" text-anchor="middle" font-size="26" font-weight="700"
    fill="var(--fg)">{failed}</text>
  <text x="{cx}" y="{cy+16}" text-anchor="middle" font-size="11" fill="var(--muted)">failed</text>
</svg>"""


def bars(data: list[tuple[str, int, int]], width: int = 460, bar_h: int = 26) -> str:
    """Horizontal stacked bars: (label, failed, total)."""
    if not data:
        return '<p class="muted">No data.</p>'
    gap, left, top = 10, 150, 6
    max_total = max((t for _, _, t in data), default=1) or 1
    plot_w = width - left - 50
    rows = []
    for i, (label, failed, total) in enumerate(data):
        y = top + i * (bar_h + gap)
        full = plot_w * total / max_total
        bad = full * (failed / total) if total else 0
        rows.append(
            f'<text x="{left-8}" y="{y+bar_h*0.68}" text-anchor="end" font-size="12" '
            f'fill="var(--fg)">{_esc(label)}</text>'
            f'<rect x="{left}" y="{y}" width="{full:.1f}" height="{bar_h}" rx="4" fill="var(--ok)"/>'
            f'<rect x="{left}" y="{y}" width="{bad:.1f}" height="{bar_h}" rx="4" fill="var(--danger)"/>'
            f'<text x="{left+full+6}" y="{y+bar_h*0.68}" font-size="11" fill="var(--muted)">'
            f'{failed}/{total}</text>'
        )
    height = top + len(data) * (bar_h + gap)
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">'
            + "".join(rows) + "</svg>")


def severity_bar(by_sev: dict[str, int], width: int = 460) -> str:
    colors = {"critical": "#b91c1c", "high": "#ea580c", "medium": "#d97706", "low": "#65a30d"}
    items = [(k, v) for k, v in by_sev.items() if v]
    total = sum(v for _, v in items)
    if not total:
        return '<p class="muted">No failures.</p>'
    x, h, segs, legend = 0, 30, [], []
    for name, count in items:
        w = width * count / total
        segs.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{h}" fill="{colors[name]}"/>')
        legend.append(
            f'<span class="chip"><i style="background:{colors[name]}"></i>{name} ({count})</span>'
        )
        x += w
    svg = f'<svg viewBox="0 0 {width} {h}" width="100%" height="{h}" role="img">{"".join(segs)}</svg>'
    return svg + f'<div class="legend">{"".join(legend)}</div>'
