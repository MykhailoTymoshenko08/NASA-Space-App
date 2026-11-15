"""What the PDF report prints: the analysis result in farmer words and US units.

Mirrors the web Analysis page (frontend `shared/lib/units`, `entities/analysis/config/labels`,
`entities/metric/lib/present`), so a value reads the same on screen and on paper. Never invents a value:
a missing one prints "Not available" with its reason.
"""

import math
from dataclasses import dataclass, field

from app.models import (
    AnalysisOptions,
    AnalysisResult,
    BoundaryType,
    CropYear,
    DatasetRef,
    Metric,
    Priority,
    Quality,
    ResolvedBy,
    Strategy,
    TimeSeries,
)
from app.report.charts import chart
from app.report.units import acres, display, fmt, lat_lon, long_date, resolution, short_date, source_text

PRIORITY_LABEL = {
    Priority.water_conservation: "Save water",
    Priority.extra_income: "Extra income",
    Priority.soil_health: "Soil health",
    Priority.erosion_control: "Less erosion",
    Priority.low_input_cost: "Low input cost",
    Priority.nitrogen_fixing: "Add nitrogen naturally",
}
ROLE_LABEL = {
    "cash_crop": "Cash crop",
    "cover_crop": "Cover crop",
    "nitrogen_fixer": "Nitrogen fixer",
    "forage": "Forage",
    "fallow": "Fallow",
}
CRITERION_LABEL = {
    "water_use": "Water use",
    "soil_health": "Soil health",
    "erosion": "Erosion",
    "nitrogen": "Nitrogen",
    "pest_cycle": "Pest cycle",
    "income": "Income index",
    "climate_risk": "Climate risk",
}
QUALITY_LABEL = {
    Quality.measured: "Measured",
    Quality.modeled: "Modeled",
    Quality.estimated: "Estimated",
    Quality.unavailable: "Unavailable",
}
# Table groups of the design (page 4), in order. Unknown categories go last, never dropped.
GROUPS = [
    ("Moisture", {"moisture"}),
    ("Weather", {"atmosphere", "temperature", "precipitation"}),
    ("Soil", {"soil"}),
    ("Land and plants", {"terrain", "vegetation"}),
]


@dataclass
class Season:
    label: str
    crop: str
    role: str


@dataclass
class TopicScore:
    label: str
    score: int


@dataclass
class EvidenceLine:
    statement: str
    source: str | None


@dataclass
class StrategyView:
    rank: str
    name: str
    summary: str
    score: int
    delta: str
    confidence: str
    is_best: bool
    is_current: bool
    needs_local_review: bool
    seasons: list[Season]
    topics: list[TopicScore]
    evidence: list[EvidenceLine]
    benefits: list[str]
    risks: list[str]
    gaps: list[str]


@dataclass
class ConditionRow:
    label: str
    value: str
    unit: str
    quality: str
    detail: str
    note: str | None


@dataclass
class ConditionGroup:
    title: str
    rows: list[ConditionRow] = field(default_factory=list)


@dataclass
class DatasetRow:
    dataset: str
    provider: str
    resolution: str
    period: str


def strategy_views(strategies: list[Strategy]) -> list[StrategyView]:
    """Sorted by score (stable), like the web page: index 0 is the best fit."""
    ordered = sorted(strategies, key=lambda s: -s.score)
    baseline = next((s.score for s in ordered if s.is_current), None)
    views = []
    for i, st in enumerate(ordered):
        if st.is_current:
            delta = "Baseline"
        elif baseline is None:
            delta = ""
        else:
            d = round(st.score - baseline)
            delta = f"{'+' if d >= 0 else ''}{d} vs your current rotation"
        views.append(
            StrategyView(
                rank="Best fit" if i == 0 else f"Option {i + 1}",
                name=st.name,
                summary=st.summary,
                score=round(st.score),
                delta=delta,
                confidence=f"Confidence: {st.confidence.capitalize()}",
                is_best=i == 0,
                is_current=st.is_current,
                needs_local_review=st.needs_local_review,
                seasons=[
                    Season(f"Season {r.season_index + 1}", r.crop, ROLE_LABEL.get(r.role, str(r.role)))
                    for r in sorted(st.rotation, key=lambda r: r.season_index)
                ],
                topics=[
                    TopicScore(CRITERION_LABEL.get(b.criterion, str(b.criterion)), round(b.score))
                    for b in st.score_breakdown
                ],
                evidence=[
                    EvidenceLine(
                        e.statement, source_text(e.source.dataset, e.source.provider) if e.source else None
                    )
                    for e in st.evidence
                ],
                benefits=list(st.benefits),
                risks=list(st.risks),
                gaps=list(st.information_gaps),
            )
        )
    return views


def field_size_m(area_ha: float | None) -> float | None:
    return math.sqrt(area_ha * 10_000) if area_ha and area_ha > 0 else None


def condition_row(m: Metric, size_m: float | None) -> ConditionRow:
    available = m.quality != Quality.unavailable and m.value is not None
    if not available:
        return ConditionRow(
            m.label,
            "Not available",
            "",
            QUALITY_LABEL[Quality.unavailable],
            m.unavailable_reason or "Not available right now.",
            None,
        )
    value, unit = display(m.value, m.unit)
    if m.period:
        when = f"{short_date(m.period.start)} to {long_date(m.period.end)}"
    else:
        when = long_date(m.as_of) if m.as_of else None
    coarse = m.resolution_m is not None and size_m is not None and m.resolution_m > size_m
    parts = [
        when,
        source_text(m.source.dataset, m.source.provider),
        resolution(m.resolution_m),
        "Wider than this field" if coarse else None,
    ]
    return ConditionRow(
        m.label, value, unit, QUALITY_LABEL[m.quality], " · ".join(p for p in parts if p), m.note
    )


def condition_groups(metrics: list[Metric], size_m: float | None) -> list[ConditionGroup]:
    groups = [ConditionGroup(title) for title, _ in GROUPS]
    other = ConditionGroup("Other")
    for m in metrics:
        i = next((i for i, (_, cats) in enumerate(GROUPS) if m.category in cats), None)
        (groups[i] if i is not None else other).rows.append(condition_row(m, size_m))
    return [g for g in [*groups, other] if g.rows]


def dataset_rows(datasets: list[DatasetRef]) -> list[DatasetRow]:
    return [
        DatasetRow(d.dataset, d.provider, resolution(d.resolution_m) or "", d.coverage_period or "")
        for d in datasets
    ]


def crop_history(result: AnalysisResult, options: AnalysisOptions | None) -> tuple[str, str]:
    """(label, text) for the summary: what the farmer entered, else the mapped crops, newest first."""
    entered = options is not None and options.crop_history is not None
    history: list[CropYear] = (
        list(options.crop_history or []) if entered else list(result.selection.crop_history)
    )
    label = "Crop history you entered" if entered else "Latest mapped crops"
    if not history:
        return label, result.selection.crop_class or "Not known"
    latest = sorted(history, key=lambda c: -c.year)[:3]
    return label, " · ".join(f"{c.year} {c.crop}" for c in latest)


def report_context(result: AnalysisResult, options: AnalysisOptions | None, job_id: str) -> dict:
    sel = result.selection
    buffered = (
        sel.resolved_by == ResolvedBy.buffered_point or sel.boundary_type == BoundaryType.buffered_point
    )
    county = f"{sel.county.name} County, {sel.county.state_postal}"
    kind = "Circle around your point" if buffered else "Estimated field area"
    area = (
        f"{acres(sel.area_ha)} acres ({fmt(sel.area_ha, 1)} ha)" if sel.area_ha is not None else "Not known"
    )
    strategies = strategy_views(result.strategies)
    generated = result.generated_at
    history_label, history = crop_history(result, options)
    data_dates = [m.as_of for m in result.current_conditions if m.as_of]
    data_dates += [m.period.end for m in result.current_conditions if m.period]
    footer_ref = sel.field_id or lat_lon(sel.anchor.lat, sel.anchor.lon)
    return {
        "title": f"Rotation analysis, {county}",
        "county": county,
        "kind": kind,
        "summary": [
            (kind, area),
            ("County", county),
            ("Location", lat_lon(sel.anchor.lat, sel.anchor.lon)),
            (history_label, history),
            ("Priorities", priorities_text(options)),
            ("Looking ahead", years_text(options.horizon_years) if options else "Not known"),
        ],
        "best": strategies[0],
        "strategies": strategies,
        "charts": [chart(ts) for ts in result.time_series],
        "history_title": history_title(result.time_series),
        "conditions": condition_groups(result.current_conditions, field_size_m(sel.area_ha)),
        "datasets": dataset_rows(result.datasets_used),
        "warnings": list(result.warnings),
        "disclaimer": result.disclaimer,
        "model_version": result.model_version,
        "generated": long_date(generated.date()),
        "data_as_of": long_date(max(data_dates)) if data_dates else None,
        "footer": f"{kind} {footer_ref} · Report {job_id[:8]} · Generated {long_date(generated.date())}",
    }


def priorities_text(options: AnalysisOptions | None) -> str:
    if options is None:
        return "Not known"
    return ", ".join(PRIORITY_LABEL[p] for p in options.priorities) or "Balanced"


def years_text(n: int) -> str:
    return f"{n} {'year' if n == 1 else 'years'}"


def history_title(series: list[TimeSeries]) -> str:
    """ "The last 6 months" (design copy) when the charts span about that; otherwise a neutral title."""
    dates = [p.t for ts in series for p in ts.points]
    if len(dates) < 2:
        return "Recent history"
    days = (max(dates) - min(dates)).days
    return "The last 6 months" if 150 <= days <= 200 else "Recent history"
