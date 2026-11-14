# Contract changelog

`openapi.yaml` is the source of truth. `openapi.json` is generated from it
(`cd backend && make contract-json`). Every change bumps `info.version` and gets an entry here.

## 0.3.0 (2026-11-14): CSB field polygons for IA, IL, NE; PLSS removed

Breaking. The selectable unit is again an **estimated field area** from USDA Crop Sequence Boundaries
(CSB), now only for Iowa, Illinois and Nebraska. PLSS sections (0.2.0) are removed. Elsewhere in CONUS a
point resolves to a buffered point, as before.

- `FieldSelection`:
  - `boundary_type` enum is `[estimated_csb, buffered_point]`. `plss_section` is removed.
  - `plss` (`PlssRef`) and `label` are removed. `PlssRef` schema is removed.
  - `crop_class` (latest CDL crop name) and `crop_history` (`[{year, crop}]`, newest first, up to 8 years)
    are filled from CSB again. Empty for buffered points.
- `FieldId` is `csb<edition>_<CSBID>` (e.g. `csb2025_190000123456`); the CSB id is only unique within
  one edition.
- `GET /tiles/fields/{z}/{x}/{y}.mvt` is removed. Field polygons are one static PMTiles file hosted
  outside the backend.
- `Coverage`:
  - `bounds` is the bbox of the supported states; `supported_states` is `["IA","IL","NE"]`.
  - `field_tiles.format` (new, required, `pmtiles`); `field_tiles.unit` enum is `[estimated_csb]`;
    `url_template` is the absolute URL of the `.pmtiles` file (source layer `fields`, props `field_id`,
    `crop_class`, `area_ha`); `regions` are the three states.
  - `field_boundary_source.boundary_type` enum is `[estimated_csb]`.
- `GET /geo/states` lists only the supported states. `GET /geo/states/{fips}/counties` returns
  `404 NOT_FOUND` for any other state; listed counties all have `has_field_coverage: true`.
- Boundary tiles lose the `townships` layer (`states`, `counties` only).
- `AnalysisRequest.options.crop_history` stays: an optional farmer correction that replaces the mapped
  history.

## 0.2.1 (2026-11-14)

Additive only. These two items were in the backend's earlier 0.2.0 draft and were left out of the
team's PLSS 0.2.0 file.

- `POST /locations/resolve` documents `429 RATE_LIMITED` (with `Retry-After`), like `POST /analyses`.
  Both endpoints are rate-limited per client IP.
- `Metric.unit` documents `fraction` (0 to 1). `Metric.key` documents `soil_wetness_surface` and
  `soil_wetness_rootzone`: NASA POWER modeled soil wetness, unit `fraction`. They are modeled, not
  satellite-measured, so they are separate from the SMAP keys `soil_moisture_*` (`m3/m3`).

## 0.2.0 (2026-11-14): PLSS sections replace crop field polygons

The selectable unit is now a BLM PLSS survey section (about 1 square mile / 640 acres), not a farm
field. API names (`/fields`, `field_id`, `FieldSelection`) are unchanged: "field" now means
"selectable land unit". The UI must say "survey section".

- `FieldSelection`:
  - new required `boundary_type`: `plss_section`, `buffered_point`, or (reserved) `estimated_csb`.
  - new `plss` (`PlssRef`: `township_id`, `section_id`, `section_number`, `division_type`); null for
    buffered points.
  - new `label`, e.g. "Section 14, T80N R24W"; null for buffered points.
  - `crop_class` is always null and `crop_history` always `[]`: PLSS has no crop data.
- `FieldId` is `plss:` + BLM First Division id (+ `-<dup>` suffix when BLM marks a duplicate).
- `Coverage`:
  - `field_boundary_source` is now required: `{name, edition, boundary_type, attribution}`.
  - `field_tiles.unit` is required (`plss_section`).
  - `regions` lists the areas that actually have PLSS data, not all of CONUS.
- `County.has_field_coverage` is true when the county intersects at least one section.
- Tiles: `fields` features are sections with `label`; `crop_class` is an empty string.
  Boundary tiles gain a `townships` layer (`township_id`, `label`) for zoom 8 to 10.
- `AnalysisRequest.options.crop_history` is the only crop history source.

## 0.1.0

Initial contract.
