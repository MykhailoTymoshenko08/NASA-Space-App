"""Compare 2-4 of a farmer's saved fields side by side, with money at each field's asking rent.

Data per field:
- Soil, from the field snapshot (`/snapshots`): SSURGO area-weighted over the estimated field area,
  including the NCCPI soil productivity index.
- Slope, drainage, land cover and long-term climate, from the saved `/fields/info` context. A field saved
  without it is fetched live once (same deadline as `/fields/info`) and not stored.
- Money, from the rotation budget (`app.profitability.rotation`) for one shared crop plan. Yields and prices
  are state references, so money differs between fields only through rent, previous crop and size. The
  response says so; soil quality is judged from the soil rows, never turned into a yield.

`build_comparison` is pure (no I/O) so the ranking rules are testable without a database or network.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pyproj import Geod
from starlette.concurrency import run_in_threadpool

from app.comparisons.history import PATTERN_LABELS, crop_kind, summarize_history
from app.core.errors import ApiException, ErrorCode, not_found
from app.geo.resolve import get_field_selection, resolve_point
from app.models import (
    BoundaryType,
    BudgetAmounts,
    ComparedField,
    ComparisonBest,
    ComparisonCell,
    ComparisonPlan,
    ComparisonRow,
    CropHistorySummary,
    FieldComparison,
    FieldInfo,
    FieldSelection,
    LatLon,
    Metric,
    Quality,
    RentUsed,
    RotationBudget,
    RotationBudgetOptions,
    SavedFieldComparisonRequest,
    SelectionSource,
    Snapshot,
    ValueRange,
)
from app.profitability import baseline
from app.profitability.money import money
from app.profitability.rotation import estimate_rotation_budget

log = logging.getLogger(__name__)

LABELS = "ABCD"
PH_TARGET = ValueRange(min=6.0, max=7.0)
STEEP_SLOPE_PCT = 6.0
DISCLAIMER = (
    "Field Shift compares public USDA and NASA data and illustrative budgets. It is not an appraisal or a "
    "yield forecast. Walk the fields, check drainage tile, fertility tests and lease terms, and talk to "
    "your local extension office or farm manager before you sign a lease."
)
MONEY_NOTE = (
    "Illustrative budget at base prices, average per year over the plan. Yields and prices are state "
    "references, the same for every field in a state."
)


@dataclass(frozen=True)
class FieldInput:
    """Everything `build_comparison` needs about one saved field (already fetched)."""

    saved_field_id: UUID
    name: str
    field_id: str | None
    state: str
    centroid: LatLon
    area_ha: float | None
    farmer_history: list[tuple[int, str]] | None
    selection: FieldSelection
    snapshot: Snapshot | None
    info: FieldInfo | None
    info_as_of: datetime | None
    rent: float | None  # farmer's asking rent, USD/acre/year


# ---------- money ----------

def _sequence(plan: ComparisonPlan, previous: str | None) -> list[dict]:
    """The plan's rotation over the horizon, starting with the crop that follows the field's last crop."""
    rotation = [c.value for c in plan.rotation]
    kind = crop_kind(previous)
    start = (rotation.index(kind) + 1) % len(rotation) if kind in rotation else 0
    return [{"year": y + 1, "season": "main", "crop": rotation[(start + y) % len(rotation)]}
            for y in range(plan.horizon_years)]


def _rent_used(state: str, farmer: float | None) -> RentUsed:
    if farmer is not None:
        return RentUsed(per_acre=money(farmer), source="farmer", is_placeholder=False)
    entry = baseline.DATA["land_rent"].get(state)
    if entry is None:
        return RentUsed(per_acre=None, source="none", is_placeholder=False)
    if entry.get("placeholder"):
        return RentUsed(per_acre=None, source="state_baseline", is_placeholder=True)
    return RentUsed(per_acre=money(entry["value"]), source="state_baseline",
                    is_placeholder=bool(entry.get("placeholder")))


def _amounts(budget: RotationBudget | None, pick: Callable) -> BudgetAmounts | None:
    avg = budget.annual_average if budget else None
    if avg is None:
        return None
    values = {k: pick(getattr(avg, k)) for k in ("low", "base", "high")}
    if any(v is None for v in values.values()):
        return None
    return BudgetAmounts(**values)


# ---------- rows ----------

def _metric(metrics: Sequence[Metric] | None, key: str) -> Metric | None:
    return next((m for m in metrics or () if m.key == key), None)


def _cell(fid: UUID, m: Metric | None, missing: str) -> ComparisonCell:
    if m is None:
        return ComparisonCell(saved_field_id=fid, value=None, quality=Quality.unavailable, note=missing)
    if m.quality == Quality.unavailable or m.value is None:
        return ComparisonCell(saved_field_id=fid, value=None, quality=Quality.unavailable,
                              note=m.unavailable_reason or missing)
    return ComparisonCell(saved_field_id=fid, value=m.value, quality=m.quality, note=m.note)


def _value(fid: UUID, value: float | str | None, quality: Quality, note: str | None = None,
           missing: str = "Not available.") -> ComparisonCell:
    if value is None:
        return ComparisonCell(saved_field_id=fid, value=None, quality=Quality.unavailable, note=missing)
    return ComparisonCell(saved_field_id=fid, value=value, quality=quality, note=note)


def _comparable(cells: Sequence[ComparisonCell]) -> list[tuple[UUID, float]]:
    return [(c.saved_field_id, float(c.value)) for c in cells
            if c.quality != Quality.unavailable and isinstance(c.value, int | float)
            and not isinstance(c.value, bool)]


def best_of(cells: Sequence[ComparisonCell], better: str, target: ValueRange | None = None) -> list[UUID]:
    """Ids with the best value. Empty when fewer than two values compare or every value ties."""
    values = _comparable(cells)
    if better == "none" or len(values) < 2:
        return []

    def score(v: float) -> float:
        if better == "higher":
            return v
        if better == "lower":
            return -v
        assert target is not None
        return -max(target.min - v, 0.0, v - target.max)

    top = max(score(v) for _, v in values)
    best = [fid for fid, v in values if abs(score(v) - top) < 1e-9]
    return [] if len(best) == len(values) else best


def _same_for_all(cells: Sequence[ComparisonCell]) -> bool:
    if len(cells) < 2 or any(c.quality == Quality.unavailable for c in cells):
        return False
    first = cells[0].value
    if isinstance(first, int | float):
        return all(isinstance(c.value, int | float) and abs(float(c.value) - float(first)) < 1e-9
                   for c in cells)
    return all(c.value == first for c in cells)


def _row(key: str, label: str, group: str, unit: str, better: str, cells: list[ComparisonCell],
         note: str | None = None, target: ValueRange | None = None) -> ComparisonRow:
    return ComparisonRow(
        key=key, label=label, group=group, unit=unit, better=better, target=target, cells=cells,
        best=best_of(cells, better, target), same_for_all=_same_for_all(cells), note=note,
    )


# ---------- whole comparison ----------

@dataclass
class _Computed:
    inp: FieldInput
    label: str
    history: CropHistorySummary
    rent: RentUsed
    budget: RotationBudget | None
    net: BudgetAmounts | None
    net_field: BudgetAmounts | None
    break_even: BudgetAmounts | None
    nccpi: float | None
    rent_per_point: float | None
    distance_km: float | None


def _compute(inp: FieldInput, label: str, plan: ComparisonPlan, overrides, home: LatLon | None) -> _Computed:
    if inp.farmer_history:
        history = summarize_history(inp.farmer_history, "farmer")
    else:
        history = summarize_history([(c.year, c.crop) for c in inp.selection.crop_history], "usda_csb")
    rent = _rent_used(inp.state, inp.rent)
    budget = None
    if rent.source != "none":
        budget = estimate_rotation_budget(
            _sequence(plan, history.latest_crop), inp.state, inp.area_ha,
            RotationBudgetOptions(land_rent_per_acre=inp.rent, crop_overrides=overrides),
            previous_crop=history.latest_crop,
        )
    m = _metric(inp.snapshot.metrics if inp.snapshot else None, "soil_productivity_nccpi")
    rated = m is not None and m.quality != Quality.unavailable and isinstance(m.value, int | float)
    nccpi = float(m.value) if rated else None
    per_point = round(rent.per_acre / nccpi, 2) if nccpi and rent.per_acre is not None else None
    distance = None
    if home is not None:
        _, _, metres = Geod(ellps="WGS84").inv(home.lon, home.lat, inp.centroid.lon, inp.centroid.lat)
        distance = round(metres / 1000, 1)
    return _Computed(
        inp=inp, label=label, history=history, rent=rent, budget=budget,
        net=_amounts(budget, lambda s: s.profit_per_acre),
        net_field=_amounts(budget, lambda s: s.field_profit),
        break_even=_amounts(budget, lambda s: s.return_before_land_per_acre),
        nccpi=nccpi, rent_per_point=per_point, distance_km=distance,
    )


def _rent_note(f: _Computed) -> str:
    if f.rent.source == "farmer":
        return "Your asking rent."
    if f.rent.is_placeholder:
        return f"State placeholder rent for {f.inp.state}, not sourced data. Enter the asking rent."
    entry = baseline.DATA["land_rent"].get(f.inp.state)
    year = entry["data_years"] if entry else "Unknown year"
    return f"{year} state reference for {f.inp.state}, not a local lease quote."


def _history_note(f: _Computed) -> str | None:
    h = f.history
    if h.source == "none":
        return None
    who = "Your record" if h.source == "farmer" else "USDA crop maps"
    return f"{who}, {h.first_year} to {h.latest_year}."


def _rows(fields: list[_Computed], home: LatLon | None) -> list[ComparisonRow]:
    no_budget = "No complete budget for this plan in this state."
    no_info = "Field context is missing. Refresh this field on My fields."
    no_soil = "Soil data is not available right now. Try again in a minute."
    no_history = "No crop history on record."
    est = Quality.estimated

    def money(pick, missing: str = no_budget) -> list[ComparisonCell]:
        return [_value(f.inp.saved_field_id, pick(f), est, missing=missing) for f in fields]

    def info(key: str) -> list[ComparisonCell]:
        return [_cell(f.inp.saved_field_id, _metric(f.inp.info.metrics if f.inp.info else None, key), no_info)
                for f in fields]

    def soil(key: str) -> list[ComparisonCell]:
        return [_cell(f.inp.saved_field_id,
                      _metric(f.inp.snapshot.metrics if f.inp.snapshot else None, key), no_soil)
                for f in fields]

    def history(pick) -> list[ComparisonCell]:
        return [_value(f.inp.saved_field_id, pick(f.history) if f.history.source != "none" else None, est,
                       _history_note(f), missing=no_history) for f in fields]

    per_acre = "USD/acre/year"
    rows = [
        _row("net_return_per_acre", "Return after rent, per acre", "money", per_acre, "higher",
             money(lambda f: f.net.base if f.net else None), MONEY_NOTE),
        _row("net_return_field", "Return after rent, whole field", "money", "USD/year", "higher",
             money(lambda f: f.net_field.base if f.net_field else None,
                   "Needs a mapped field area and a complete budget."),
             "Per-acre return times the estimated field area."),
        _row("break_even_rent", "Highest rent the field can carry", "money", per_acre, "higher",
             money(lambda f: f.break_even.base if f.break_even else None),
             "Return before land at base prices: rent above this loses money in an average year."),
        _row("rent", "Cash rent used", "money", per_acre, "lower",
             [_value(f.inp.saved_field_id, f.rent.per_acre, est, _rent_note(f),
                     missing="No rent for this state. Enter the asking rent.") for f in fields]),
        _row("rent_per_productivity_point", "Rent per soil productivity point", "money", "USD/acre/point",
             "lower", money(lambda f: f.rent_per_point, "Needs a rent and a soil productivity rating."),
             "Rent divided by the NCCPI rating. Lower means more soil for the money."),
        _row("area", "Field size", "land", "ha", "none",
             [_value(f.inp.saved_field_id, f.inp.area_ha, est,
                     "Estimated field area (USDA crop sequence boundaries).",
                     missing="Saved as a point: no field area.") for f in fields]),
        _row("slope", "Slope", "land", "%", "lower", info("slope")),
        _row("land_cover", "Land cover", "land", "class", "none", info("land_cover")),
    ]
    if home is not None:
        rows.append(_row("distance_from_home", "Distance from your farm", "land", "km", "lower",
                         [_value(f.inp.saved_field_id, f.distance_km, Quality.measured,
                                 "Straight-line distance, not road distance.") for f in fields]))
    rows += [
        _row("soil_productivity_nccpi", "Soil productivity (NCCPI)", "soil", "index", "higher",
             soil("soil_productivity_nccpi"),
             "USDA rating from 0 to 100 for non-irrigated commodity crops. Higher is better."),
        _row("soil_organic_matter_pct", "Organic matter", "soil", "%", "higher",
             soil("soil_organic_matter_pct")),
        _row("soil_ph", "Soil pH", "soil", "pH", "target", soil("soil_ph"),
             "Most corn and soybean ground does best between pH 6.0 and 7.0.", PH_TARGET),
        _row("soil_texture_class", "Soil texture", "soil", "class", "none", soil("soil_texture_class")),
        _row("soil_drainage", "Drainage class", "soil", "class", "none", info("soil_drainage"),
             "Poorly drained soils can be very productive when tiled. Ask about drainage tile."),
        _row("rotation_pattern", "Recent rotation", "history", "class", "none",
             history(lambda h: PATTERN_LABELS[h.pattern])),
        _row("latest_crop", "Last crop", "history", "class", "none", history(lambda h: h.latest_crop)),
        _row("corn_in_a_row", "Corn years in a row", "history", "years", "lower",
             history(lambda h: h.corn_in_a_row),
             "Corn after corn usually needs more nitrogen and has more pest pressure."),
        _row("precipitation_normal", "Rain per year, long-term", "climate", "mm", "none",
             info("precipitation_normal"), "Regional climate: grid cells are much larger than a field."),
        _row("temperature_normal", "Average temperature, long-term", "climate", "degC", "none",
             info("temperature_normal"), "Regional climate: grid cells are much larger than a field."),
    ]
    return rows


def _notes(f: _Computed, rows: list[ComparisonRow]) -> tuple[list[str], list[str]]:
    fid = f.inp.saved_field_id
    by_key = {r.key: r for r in rows}

    def wins(key: str) -> bool:
        return key in by_key and fid in by_key[key].best

    strengths, cautions = [], []
    if wins("net_return_per_acre"):
        strengths.append("Highest return after rent per acre of these fields.")
    if wins("soil_productivity_nccpi"):
        strengths.append(f"Most productive soil of these fields (NCCPI {f.nccpi:g}).")
    if wins("rent_per_productivity_point"):
        strengths.append("Lowest rent for each point of soil productivity.")
    if f.history.pattern == "corn_soybean":
        strengths.append("Corn and soybeans in turn: corn after soybeans needs less nitrogen.")

    if f.net is not None and f.net.base < 0 and f.rent.per_acre is not None:
        cautions.append(f"Loses money at base prices with rent ${f.rent.per_acre:,.0f}/acre "
                        f"(break-even rent about ${f.break_even.base:,.0f}).")
    if f.rent.source == "state_baseline" and f.rent.is_placeholder:
        cautions.append("Rent is a state placeholder. Enter the asking rent for a real comparison.")
    if f.budget is not None and f.budget.missing_inputs:
        cautions.extend(f.budget.missing_inputs)
    if f.history.corn_in_a_row >= 3:
        cautions.append(f"Corn {f.history.corn_in_a_row} years in a row: expect higher nitrogen needs "
                        "and pest pressure.")
    slope = _metric(f.inp.info.metrics if f.inp.info else None, "slope")
    if slope and isinstance(slope.value, int | float) and slope.value >= STEEP_SLOPE_PCT:
        cautions.append(f"Slope about {slope.value:g}%: check erosion control (terraces, waterways).")
    cover = _metric(f.inp.info.metrics if f.inp.info else None, "land_cover")
    if cover and isinstance(cover.value, str) and cover.value != "Cultivated crops":
        cautions.append(f"The land-cover map shows {cover.value.lower()}, not cropland, at the sample point.")
    if f.inp.selection.boundary_type == BoundaryType.buffered_point:
        cautions.append("No mapped field boundary: soil is read around a point, not over the field.")
    if f.inp.snapshot is None:
        cautions.append("Soil data could not be loaded right now.")
    if f.inp.info is None:
        cautions.append("Field context (slope, drainage, climate) is missing. Refresh it on My fields.")
    return strengths, cautions


def build_comparison(
    inputs: Sequence[FieldInput], plan: ComparisonPlan, crop_overrides=(), home: LatLon | None = None,
    now: datetime | None = None,
) -> FieldComparison:
    computed = [_compute(inp, LABELS[i], plan, list(crop_overrides), home) for i, inp in enumerate(inputs)]
    rows = _rows(computed, home)
    by_key = {r.key: r for r in rows}
    fields = []
    for f in computed:
        strengths, cautions = _notes(f, rows)
        fields.append(ComparedField(
            saved_field_id=f.inp.saved_field_id, label=f.label, name=f.inp.name, field_id=f.inp.field_id,
            state=f.inp.state, county=f.inp.selection.county, anchor=f.inp.centroid,
            boundary_type=f.inp.selection.boundary_type, area_ha=f.inp.area_ha, rent=f.rent, budget=f.budget,
            net_return_per_acre=f.net, net_return_field=f.net_field, break_even_rent_per_acre=f.break_even,
            history=f.history, strengths=strengths, cautions=cautions,
            data_as_of=f.inp.snapshot.generated_at if f.inp.snapshot else None, info_as_of=f.inp.info_as_of,
        ))

    warnings = [
        "Money rows are illustrative budgets. Yields and prices are state references, so between fields in "
        "one state they differ only by rent, the previous crop and field size. Judge land quality from the "
        "soil rows.",
    ]
    placeholder_states = sorted({f.inp.state for f in computed
                                 if f.rent.source == "state_baseline" and f.rent.is_placeholder})
    if placeholder_states:
        warnings.append(f"Rent for {', '.join(placeholder_states)} uses an unsourced state placeholder. "
                        "Enter the asking rent for each field.")
    if len({f.inp.state for f in computed}) > 1:
        warnings.append("These fields are in different states: yields, prices and costs use each state's "
                        "references.")
    if any(f.budget is not None and f.budget.uses_placeholders for f in computed):
        warnings.append("Some budget inputs are placeholders, not sourced data.")
    return FieldComparison(
        generated_at=(now or datetime.now(UTC)).replace(microsecond=0), plan=plan, fields=fields, rows=rows,
        best=ComparisonBest(
            net_return=by_key["net_return_per_acre"].best,
            soil_productivity=by_key["soil_productivity_nccpi"].best,
            rent_value=by_key["rent_per_productivity_point"].best,
        ),
        warnings=warnings, disclaimer=DISCLAIMER,
    )


# ---------- I/O ----------

def _selection(svc, row: dict) -> FieldSelection:
    """The CSB field when the saved field has one, else the saved centroid (no snapping to a neighbour)."""
    if row["field_id"] and svc.fields is not None:
        try:
            return get_field_selection(svc, row["field_id"], SelectionSource.coordinates)
        except ApiException as e:
            if e.code != ErrorCode.NOT_FOUND:
                raise
            log.info("saved field %s: CSB id %s is gone, using its centroid", row["id"], row["field_id"])
    point = LatLon(lat=row["centroid_lat"], lon=row["centroid_lon"])
    return resolve_point(svc, point, snap_radius_m=0, source=SelectionSource.coordinates)


async def _snapshot(svc, selection: FieldSelection) -> Snapshot | None:
    try:
        return await svc.snapshots.snapshot(selection)
    except Exception:  # noqa: BLE001 - a missing snapshot is shown per field, never fails the comparison
        log.warning("comparison snapshot failed", exc_info=True)
        return None


async def _info(svc, row: dict) -> tuple[FieldInfo | None, datetime | None]:
    if row["info"]:
        return FieldInfo.model_validate(row["info"]), row["info_fetched_at"]
    try:
        info = await svc.field_info.info(LatLon(lat=row["centroid_lat"], lon=row["centroid_lon"]))
    except Exception:  # noqa: BLE001
        log.warning("comparison field info failed", exc_info=True)
        return None, None
    if all(m.quality == Quality.unavailable for m in info.metrics):
        return None, None
    return info, info.generated_at


async def compare_saved_fields(
    svc, store, user_id: UUID, req: SavedFieldComparisonRequest,
) -> FieldComparison:
    def load() -> list[tuple[dict, FieldSelection]]:
        out = []
        for sid in req.saved_field_ids:
            row = store.get(user_id, sid)
            if row is None:
                raise not_found("Saved field not found.", saved_field_id=str(sid))
            out.append((row, _selection(svc, row)))
        return out

    loaded = await run_in_threadpool(load)
    snapshots, infos = await asyncio.gather(
        asyncio.gather(*(_snapshot(svc, sel) for _, sel in loaded)),
        asyncio.gather(*(_info(svc, row) for row, _ in loaded)),
    )
    inputs = []
    for (row, sel), snap, (info, info_as_of) in zip(loaded, snapshots, infos, strict=True):
        history = [(int(c["year"]), c["crop"]) for c in row["crop_history"]] if row["crop_history"] else None
        inputs.append(FieldInput(
            saved_field_id=row["id"], name=row["name"], field_id=row["field_id"], state=row["state"].strip(),
            centroid=LatLon(lat=row["centroid_lat"], lon=row["centroid_lon"]), area_ha=row["area_ha"],
            farmer_history=history, selection=sel, snapshot=snap, info=info, info_as_of=info_as_of,
            rent=req.rent_per_acre.get(str(row["id"])),
        ))
    return build_comparison(inputs, req.plan, req.crop_overrides, req.home)

