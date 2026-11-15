# Field comparison: frontend guide

Backend contract 0.12.0 (`contract/openapi.yaml`, tag `comparisons`). This guide explains how to build the
compare screens on top of it. The contract stays the source of truth for shapes. This file covers
behaviour, rendering rules and gotchas.

Implementation status (2026-11-15): My fields now calls `/comparisons/saved-fields` through
`entities/comparison`, with asking rents, a shared crop plan, summary cards and grouped responsive rows.
Changes apply with **Update comparison**, so editing rents does not spend requests on each keystroke.
Above the rows, three quick answers show the server's `best.net_return`, `best.soil_productivity` and
`best.rent_value`, and each field card shows its outline, return range, strengths and cautions. In the
rows, the server's best cell is tinted and labelled "Best"; rows with `same_for_all` fold into one line
(except money rows) until the user opens them. Phones stack 3 or 4 fields two per line.
The area-ranking screen and its map integration remain unimplemented; the area endpoint is tested.
See [comparison-validation.md](comparison-validation.md) for the tested scope and browser test commands.
The remaining sections are API guidance, including suggestions for those unfinished screens.

Who it is for: a farmer choosing which field to rent. They pick candidates on the map, save them, enter
the owner's asking rent and see which field pays and which has the better soil.

Two endpoints, both need the bearer token (signed-in users only):

| Endpoint | Use | Size |
| --- | --- | --- |
| `POST /comparisons/saved-fields` | Side by side, one column per field | 2 to 4 saved fields |
| `POST /comparisons/area` | Screen and rank every field of a county or a survey township | up to 30,000 fields, paged |

The usual path: rank an area, pick 2 to 4 promising fields, save them, then compare them side by side.

---

## 1. Setup

```bash
cd frontend && npm run gen:api   # already run for 0.12.0: schema.gen.ts has the new types
```

Add aliases to `src/shared/api/index.ts`:

```ts
export type FieldComparison = S["FieldComparison"];
export type SavedFieldComparisonRequest = S["SavedFieldComparisonRequest"];
export type ComparedField = S["ComparedField"];
export type ComparisonRow = S["ComparisonRow"];
export type ComparisonCell = S["ComparisonCell"];
export type AreaRankingRequest = S["AreaRankingRequest"];
export type AreaRanking = S["AreaRanking"];
export type RankedField = S["RankedField"];
export type CropHistorySummary = S["CropHistorySummary"];
```

An API module in the same style as `entities/saved-field/api/saved-fields-api.ts`:

```ts
export const comparisonsApi = {
  compare: (body: SavedFieldComparisonRequest) => unwrap(api.POST("/comparisons/saved-fields", { body })),
  rankArea: (body: AreaRankingRequest) => unwrap(api.POST("/comparisons/area", { body })),
};
```

Current FSD placement: `entities/comparison` owns the typed comparison API;
`widgets/saved-fields/ui/FieldsCompare.tsx` renders its settings, quick answers and field cards,
`CompareTable.tsx` the grouped rows, and `lib/compare.ts` the unit and money formatting.
The widget uses one comparison request instead of separate `POST /snapshots` calls.
Suggested placement for the unfinished area screen: `widgets/area-ranking` (list and map highlight).

---

## 2. Compare saved fields: `POST /comparisons/saved-fields`

### Request

```json
{
  "saved_field_ids": ["261d324b-…", "f98500da-…"],
  "rent_per_acre": { "261d324b-…": 260 },
  "plan": { "rotation": ["corn", "soybean"], "horizon_years": 2 },
  "crop_overrides": [],
  "home": { "lat": 41.98, "lon": -93.62 }
}
```

| Key | Required | Notes |
| --- | --- | --- |
| `saved_field_ids` | yes | 2 to 4 unique ids from `GET /me/fields`. Columns come back in this order, labelled `A` to `D`. |
| `rent_per_acre` | no | Asking cash rent in USD per acre per year, keyed by saved field id. Fields left out use the state reference rent, which is still a placeholder (flagged). `0` means no land charge, for land the farmer owns. Keys must be in `saved_field_ids` (else 422). Range 0 to 5000. |
| `plan` | no | Crop plan budgeted on every field. Default corn then soybean over 2 years. Crops: `corn`, `soybean`, `winter_wheat`, 1 to 3 of them. `horizon_years` 1 to 5. |
| `crop_overrides` | no | The farmer's own revenue and non-land cost per crop (`CropBudgetInput`, same as the analysis budget form). Applied to every field. |
| `home` | no | The farmstead. Adds a `distance_from_home` row. Keep it in the profile or in local storage. |

Each field starts the plan with the crop that follows its last crop. After corn, a corn/soybean plan
starts with soybeans, so the soybean nitrogen credit lands on the right year. Say this in the UI near
the plan picker: "Each field starts with the crop that follows its last crop."

### Response, in short

```ts
FieldComparison {
  generated_at, plan,
  fields: ComparedField[],   // columns, request order, label "A".."D"
  rows: ComparisonRow[],     // ready to render, already ranked
  best: { net_return: id[], soil_productivity: id[], rent_value: id[] },
  warnings: string[],        // show above the table
  disclaimer: string,        // show below the table
}
```

`ComparedField` (one column):

| Key | Use |
| --- | --- |
| `label`, `name` | Column header ("A · North 80"). Put the same letter on the map marker. |
| `county`, `state`, `area_ha`, `boundary_type` | Subtitle. For `boundary_type: buffered_point`, say "Point, no mapped field". |
| `rent` | `{per_acre, source: farmer, state_baseline or none, is_placeholder}`. Pre-fill the rent input from it. |
| `net_return_per_acre`, `net_return_field`, `break_even_rent_per_acre` | `{low, base, high}` or null. Base is the headline; low and high are the price range (historical price sensitivity, not a forecast). |
| `budget` | The full `RotationBudget`, same shape as `Strategy.budget`. Reuse the existing budget breakdown component for a "How is this calculated?" drawer. |
| `history` | `CropHistorySummary`: `pattern`, `latest_crop`, `corn_in_a_row`, counts, `source` (`farmer` or `usda_csb`). |
| `strengths`, `cautions` | Plain-English bullets, safe to show as they are. Cautions cover a loss at this rent, a placeholder rent, corn 3+ years in a row, slope of 6% or more, land not mapped as cropland, no mapped boundary and missing data. |
| `data_as_of`, `info_as_of` | "Soil data from …". Null `data_as_of` means soil could not be loaded. |

`ComparisonRow`:

```ts
{
  key: "soil_ph", label: "Soil pH", group: "soil", unit: "pH",
  better: "target", target: { min: 6.0, max: 7.0 },
  cells: [{ saved_field_id, value: 6.4, quality: "measured", note: "Area-weighted over…" }, …],
  best: ["261d324b-…"],   // highlight these cells
  same_for_all: false,
  note: "Most corn and soybean ground does best between pH 6.0 and 7.0."
}
```

Rows in 0.12.0, in this order, by `group`:

| Group | Keys |
| --- | --- |
| money | `net_return_per_acre`, `net_return_field`, `break_even_rent`, `rent`, `rent_per_productivity_point` |
| land | `area`, `slope`, `land_cover`, `distance_from_home` (only with `home`) |
| soil | `soil_productivity_nccpi`, `soil_organic_matter_pct`, `soil_ph`, `soil_texture_class`, `soil_drainage` |
| history | `rotation_pattern`, `latest_crop`, `corn_in_a_row` |
| climate | `precipitation_normal`, `temperature_normal` |

New keys may appear later. Render unknown keys generically, as you already do for metrics.

### Rendering rules

1. **Do not compute winners.** Highlight cells whose `saved_field_id` is in `row.best` (bold value, a
   "Best" chip or a check mark; never color alone). `best` is empty when the row does not rank
   (`better: none`), when fewer than two values compare, or when every value ties.
2. **`same_for_all: true`**: the row does not tell the fields apart. Fold these rows under a
   "Same for all fields" disclosure, or dim them. Expect this often for money rows between fields in
   one state, and for climate.
3. **Unavailable cells** (`quality: "unavailable"`, `value: null`): show "Not available" and the
   `note` (the reason) in a tooltip or a small line. Never show 0.
4. **Quality label**: show `QUALITY[cell.quality].label` (from `entities/metric`) on soil, land and climate
   cells, as on the field page. Money cells are always `estimated`, so label the money group once
   ("Illustrative budget") instead of on every cell.
5. **Units**: `row.unit` uses the metric codes. Convert with `toDisplay(value, unit)` from `shared/lib`
   (`ha` to acres, `mm` to in, `degC` to °F, `%`, `pH`, `class` and `index` unchanged). New units:
   - `USD/acre/year`, `USD/year`: format as money (`-$7`, `$1,337`). Show losses as losses, with a
     minus sign and text, not only red.
   - `USD/acre/point`: `$3.17 per point`.
   - `km` (`distance_from_home`, `RankedField.distance_km`): `toDisplay` does not handle it yet, so
     convert to miles (× 0.621371).
   - `years`: plain integer.
6. **`better: target`** (pH): show the target range in the row header ("best 6.0 to 7.0").
7. **Row notes**: `row.note` goes in the row header as a short help line or an info button.
8. **Warnings** go above the table. The first one always says the money rows are illustrative state
   budgets. Keep it visible: it stops farmers from reading the money difference as a soil difference.
9. **Disclaimer** goes below the table.

### Layout

- Desktop: the existing table pattern (sticky first column with label and unit, one column per field),
  grouped by `group` with group headings (Money, Land, Soil, History, Climate). Put a summary strip above
  it: one card per field with the letter, name, base return per acre, break-even rent, `strengths` and
  `cautions`.
- Phone: one card per field in a horizontal swipe (scroll-snap) showing the summary, then the rows as a
  list. In the list, each row shows two fields side by side with a field switcher (A/B/C/D chips), or
  stacks all values under the row label. Keep tap targets at 44 px or more.
- Map: draw the 2 to 4 fields with `A` to `D` markers at `field.anchor`. `home` gets a house marker.

### Asking rent inputs

- One number input per field, pre-filled from `fields[i].rent.per_acre`. When `rent.is_placeholder` is
  true, show "State placeholder: enter the asking rent".
- Re-request when a rent changes, debounced (about 600 ms). Use TanStack Query with the whole request
  body in the key and `placeholderData: keepPreviousData`, so the table does not blank while it reloads.
- The break-even rent row answers "the most I could pay". Put it next to the rent input
  ("Break-even about $263/acre").

### Timing and errors

- About 1 to 5 s on a cold cache (the soil snapshots call USDA services, up to the 4 s source deadline).
  Snapshots are cached for 24 h, so the second call is fast. Show skeleton rows.
- A failing soil or context source does not fail the request: cells become unavailable, and the field
  gets a caution such as "Soil data could not be loaded right now".

| Status | Code | When | UI |
| --- | --- | --- | --- |
| 401 | `UNAUTHORIZED` | no or expired token | the shared client refreshes; else send to sign in |
| 404 | `NOT_FOUND` | an id is not this user's (or was deleted); `details.saved_field_id` | drop it from the selection and say "One field was removed" |
| 422 | `VALIDATION_ERROR` | fewer than 2 or more than 4 ids, duplicate ids, bad rent key or value, bad plan | form validation should prevent it |
| 429 | `RATE_LIMITED` | more than 30 comparison or area requests a minute from one client; honour `Retry-After` | "Too many requests, try again in N s" |

---

## 3. Rank an area: `POST /comparisons/area`

### Request

```json
{
  "area": { "county_fips": "19169" },
  "filters": { "min_area_ha": 20, "latest_crops": ["Corn", "Soybeans"], "exclude_continuous_corn": true },
  "sort": "productivity",
  "near": { "lat": 41.98, "lon": -93.62 },
  "pinned_field_ids": ["csb2025_191825003871492"],
  "limit": 25,
  "offset": 0
}
```

`area` takes exactly one of three forms:
- `{ "county_fips": "19169" }`: from the county picker. Field states only (IA, IL, NE); another state
  gives 422 `OUTSIDE_COVERAGE`.
- `{ "bbox": [w, s, e, n] }`: for a survey township, use the `w, s, e, n` properties of the PLSS
  `townships` tile feature. They give the whole township, while tile geometry is clipped at tile edges.
  At most 1 degree on each side.
- `{ "polygon": GeoJSONPolygon }`: an outline, for example a township assembled from tiles or a shape the
  user draws. Rings must be closed, 2000 positions at most, no self-intersection.

A field belongs to the area when its interior point does.

| Key | Notes |
| --- | --- |
| `filters.min_area_ha`, `max_area_ha` | hectares (convert from acres in the UI) |
| `filters.min_productivity` | NCCPI 0 to 100. Unrated fields fail it. |
| `filters.latest_crops` | CDL names as in `crop_history` (`Corn`, `Soybeans`, …), case-insensitive |
| `filters.exclude_continuous_corn` | drops fields with corn 3 or more years in a row up to the latest year |
| `sort` | `productivity` (default, best first, unrated last), `area` (largest first), `distance` (nearest first, needs `near`) |
| `near` | adds `distance_km` to every field |
| `pinned_field_ids` | up to 4 CSB ids always reported in `pinned` with their rank and percentile, for example the fields the user already compares or saved ("Your fields in this county") |
| `limit`, `offset` | page size 1 to 100 (default 25). Next page: `offset = next_offset`. |

### Response

```ts
AreaRanking {
  area: { kind: "county" | "bbox" | "polygon", county: CountyRef | null, bbox },
  total,                  // fields matching the filters
  sort, offset, limit, next_offset,   // next_offset null on the last page
  soil: { status: "complete" | "filling" | "partial" | "unavailable", fields_rated, fields_total, method },
  stats: { area_ha: Quartiles | null, productivity: Quartiles | null },   // p25, median, p75
  items: RankedField[],
  pinned: RankedField[],
  notes: string[],
}

RankedField {
  field_id, rank, matches_filters, anchor, bbox, county_fips, area_ha,
  history: CropHistorySummary,
  productivity, soil_name, drainage,    // null until rated
  distance_km,
  area_percentile, productivity_percentile,   // 0-100 among matching fields
}
```

### Soil ratings arrive in the background (polling)

Ratings come from USDA Soil Data Access, one point per field, about 6 s per 400 fields. They are stored,
so each field is looked up only once ever. The first ranking of a new county answers at once with
`soil.status: "filling"`, then fills in:

```ts
useQuery({
  queryKey: ["area-ranking", body],
  queryFn: () => comparisonsApi.rankArea(body),
  placeholderData: keepPreviousData,
  refetchInterval: (q) => (q.state.data?.soil.status === "filling" ? 3000 : false),
});
```

- `filling`: show "Rating soil: {fields_rated} of {fields_total} fields" and a progress bar. Sorting by
  productivity reshuffles while ratings arrive, so keep the user's scroll position and do not animate
  reorders.
- `partial` or `unavailable`: the USDA service failed. The backend retries after about 2 minutes. Show
  "Soil ratings are missing for some fields. Try again in a few minutes." Rankings by size and distance
  still work.
- `complete`: stop polling.

A large county (up to 21,000 fields) takes 1 to 2 s per request once rated. Areas whose fields are all
rated are cached on the server for 5 minutes, so paging is quick.

### Rendering

- A list or table with columns: rank, field (short id plus "Polk, IA"), acres, soil productivity (value
  plus a percentile bar), soil name and drainage, last crop and `history.pattern`, distance. Each row
  has "Show on map" and "Add to compare".
- `stats` gives the area context: "Median field 12 acres; median soil 78". Show quartiles as a small
  box or range bar.
- Percentiles: "Larger than 80% of matching fields", "Better soil than 92%". They are relative to the
  matching fields, so they change when filters change; say "of matching fields".
- `pinned` is a separate block on top: "Your fields here". A pinned field that fails the filters has
  `rank: null`, `matches_filters: false`, so show "Outside your filters".
- `notes` go in a small "About this ranking" section. `soil.method` explains that ranking soil is read
  at one point (a screening value), while the side-by-side comparison reads the whole field. The two
  can differ, so show this text where both numbers appear.
- Map: fit `area.bbox`. Highlight `items` by `field_id` with feature-state on the fields PMTiles layer,
  label them with their rank, and fly to `RankedField.bbox` on "Show on map".

### From ranking to comparison

"Add to compare" needs a saved field: `GET /fields/{field_id}` gives the selection, then
`createBodyFor(selection)` and `POST /me/fields` (both exist in `entities/saved-field`). Mind the 50-field
cap (`409 FIELD_LIMIT_REACHED`). Then open the compare view with those saved field ids.

### Errors

| Status | Code | When |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` | not signed in |
| 404 | `NOT_FOUND` | unknown county FIPS |
| 422 | `OUTSIDE_COVERAGE` | county outside IA, IL, NE |
| 422 | `VALIDATION_ERROR` | bad body, `sort: distance` without `near`, box or outline larger than 1 degree, more than 30,000 fields (`details.max_fields`) |
| 429 | `RATE_LIMITED` | shared limit with the comparison endpoint |
| 500 | `INTERNAL_ERROR` | the field database is down |

---

## 4. The soil productivity index (NCCPI)

`soil_productivity_nccpi` is new in 0.12.0. It is the USDA National Commodity Crop Productivity Index
v3.0, from SSURGO, shown 0 to 100, with higher meaning better ground for non-irrigated corn, soybeans
and small grains. It also appears in `POST /snapshots` and in `AnalysisResult.current_conditions`, so
the field page shows it in the Soil group without changes. Suggested glossary text:

> Soil productivity (NCCPI): a USDA rating from 0 to 100 of how well the soil and climate suit
> non-irrigated corn, soybeans and small grains. Higher is better. It is a survey rating, not a yield
> forecast.

`rent_per_productivity_point` (rent divided by NCCPI) is the "value for money" row: land agents in Iowa
compare rents per CSR2 point the same way. Lower is better.

---

## 5. What the numbers can and cannot say

- **Money uses state references.** Yields, prices and non-land costs are state-level 2026 extension
  budgets. Two fields in one state differ in money only by rent, the previous crop and size. Soil
  quality is never turned into a yield. Use the soil rows for land quality, and say so in the UI. The
  first warning does.
- **Rent references are placeholders** until the NASS rent data is loaded. `rent.is_placeholder` and a
  warning say so. Push users to enter the asking rent.
- **CSB field areas are estimates** (algorithmic boundaries, not ownership). Keep the "estimated field
  area" wording.
- **USDA Soil Data Access is sometimes slow or down.** The compare view then shows unavailable soil cells
  and a caution. The area view shows `partial` or `unavailable` and fills later.

## 6. Mocks (MSW)

Add handlers for both routes in `shared/mocks/handlers.ts`, typed from `schema.gen.ts`. Useful scenarios:
two fields in one state (money rows `same_for_all` except rent), a point field (no area, no
`net_return_field`, soil unavailable), soil source down (all soil cells unavailable), and an area that
answers `filling` twice and then `complete`.
