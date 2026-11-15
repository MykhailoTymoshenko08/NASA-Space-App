"""Static SVG charts of a TimeSeries for the PDF (the web page draws the same data interactively).

Line for levels (soil moisture, temperature), bars for totals (rain). US units, three gridlines,
month ticks. Gaps in the data are gaps in the line, never drawn through.
"""

import math
from dataclasses import dataclass
from datetime import date

from markupsafe import Markup, escape

from app.models import TimeSeries
from app.report.units import display, display_number, long_date, resolution, short_date, source_text

W, H = 330, 150
LEFT, RIGHT, TOP, BASE = 34, 318, 10, 114
LINE = "#1F4D38"
BAR = "#4F7FB0"
GRID = "#D3CDBB"
MUTED = "#4F5A50"
# SVG text does not inherit the page font: name it, or Pango falls back to another face.
TEXT = f'font-family="Open Sans" font-size="11" fill="{MUTED}"'


@dataclass
class Chart:
    title: str
    source: str
    readout: str
    when: str
    svg: Markup | None


def is_bar(ts: TimeSeries) -> bool:
    return ts.unit == "mm" or "precip" in ts.key or "rain" in ts.key


def nice_step(span: float) -> float:
    """A round step so two steps cover the span: 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10..."""
    raw = span / 2 if span > 0 else 1
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def tick_text(v: float, step: float) -> str:
    decimals = -math.floor(math.log10(step)) if step < 1 else 0
    if step < 1 and abs(step * 10**decimals - round(step * 10**decimals)) > 1e-9:
        decimals += 1  # 0.25 needs two decimals, 0.2 one
    return f"{v:,.{decimals}f}"


def chart(ts: TimeSeries) -> Chart:
    bar = is_bar(ts)
    src = source_text(ts.source.dataset, ts.source.provider) if ts.source else ""
    if ts.source and (res := resolution(ts.source.resolution_m)):
        src = f"{src} · {res}"
    pts = [(p.t, display_number(p.v, ts.unit)[0] if p.v is not None else None) for p in ts.points]
    known = [(t, v) for t, v in pts if v is not None]
    if not known:
        return Chart(ts.label, src, "Not available", "", None)

    last_t, _ = known[-1]
    last_raw = next(p.v for p in reversed(ts.points) if p.v is not None)
    value, unit = display(last_raw, ts.unit)
    readout = f"{value} {unit}".strip()
    when = f"Week of {short_date(last_t)}" if bar else short_date(last_t)

    values = [v for _, v in known]
    lo = 0.0 if bar else min(values)
    hi = max(values)
    step = nice_step(hi - lo)
    vmin = 0.0 if bar else math.floor(lo / step) * step
    vmax = vmin + 2 * step
    while vmax < hi:  # the span can need a third step after rounding vmin down
        step = nice_step(hi - vmin)
        vmin = 0.0 if bar else math.floor(lo / step) * step
        vmax = vmin + 2 * step

    n = len(pts)
    pw = RIGHT - LEFT

    def x(i: int) -> float:
        return LEFT + (pw / 2 if n == 1 else pw * i / (n - 1))

    def y(v: float) -> float:
        return BASE - (BASE - TOP) * (v - vmin) / (vmax - vmin)

    parts = []
    for k in range(3):
        v = vmin + k * step
        gy = y(v)
        parts.append(
            f'<line x1="{LEFT}" y1="{gy:.1f}" x2="{RIGHT}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{LEFT - 6}" y="{gy + 4:.1f}" text-anchor="end" {TEXT}>{tick_text(v, step)}</text>'
        )
    if bar:
        slot = pw / max(n, 1)
        bw = max(1.0, slot * 0.72)
        for i, (_, v) in enumerate(pts):
            if v is None:
                continue
            top = y(v)
            parts.append(
                f'<rect x="{LEFT + slot * i + (slot - bw) / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                f'height="{BASE - top:.1f}" fill="{BAR}"/>'
            )
    else:
        run: list[str] = []
        runs: list[list[str]] = []
        for i, (_, v) in enumerate(pts):
            if v is None:
                if run:
                    runs.append(run)
                run = []
                continue
            run.append(f"{x(i):.1f},{y(v):.1f}")
        if run:
            runs.append(run)
        for r in runs:
            if len(r) == 1:
                cx, cy = r[0].split(",")
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{LINE}"/>')
            else:
                parts.append(
                    f'<polyline points="{" ".join(r)}" fill="none" stroke="{LINE}" stroke-width="2.5" '
                    'stroke-linejoin="round"/>'
                )
        li = max(i for i, (_, v) in enumerate(pts) if v is not None)
        parts.append(f'<circle cx="{x(li):.1f}" cy="{y(pts[li][1]):.1f}" r="4" fill="{LINE}"/>')

    parts += month_ticks([t for t, _ in pts], x)
    first, last = pts[0][0], pts[-1][0]
    label = f"{escape(ts.label)}, {long_date(first)} to {long_date(last)}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="{label}">{"".join(parts)}</svg>'
    )
    return Chart(ts.label, src, readout, when, Markup(svg))


def month_ticks(dates: list[date], x) -> list[str]:
    """A label at the first point of each month, skipping ones that would collide."""
    out, last_x = [], -100.0
    prev_month = None
    for i, t in enumerate(dates):
        if (t.year, t.month) == prev_month:
            continue
        prev_month = (t.year, t.month)
        tx = min(max(x(i), LEFT + 8), RIGHT - 8)
        if tx - last_x < 28:
            continue
        last_x = tx
        out.append(f'<text x="{tx:.1f}" y="130" text-anchor="middle" {TEXT}>{t:%b}</text>')
    return out
