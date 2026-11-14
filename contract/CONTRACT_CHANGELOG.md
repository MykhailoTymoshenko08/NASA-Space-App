# Contract changelog

`openapi.yaml` is the source of truth. `openapi.json` is generated from it
(`cd backend && make contract-json`). Every change bumps `info.version` and gets an entry here.

## 0.2.0 (2026-11-14)

Additive only. Nothing was renamed, removed, or made stricter, so 0.1.0 clients keep working.

- `FieldSelection.crop_history` (optional, array of the new `CropYear` schema `{year, crop}`, newest first).
  The list is empty when the boundary source has no multi-year history for the polygon, and always empty for
  `resolved_by = buffered_point`. Values are never guessed.
- `Coverage.field_boundary_source` (optional object): `{name, edition, estimated_csb, attribution, url}`.
  Field polygons are USDA Crop Sequence Boundaries. These are algorithmic polygons, not surveyed field
  boundaries, so `estimated_csb` is `true`. The UI should show `attribution` near the map.
- `Metric.unit` gains the documented value `fraction` (0 to 1). It is used by NASA POWER modeled soil
  wetness (`soil_wetness_surface`, `soil_wetness_rootzone`). These are new metric keys. They are modeled,
  not satellite-measured, so they are separate from the SMAP keys `soil_moisture_*` (`m3/m3`).
- `POST /locations/resolve` documents `429 RATE_LIMITED` (with `Retry-After`), like `POST /analyses`.
  Both endpoints are rate-limited per client IP.
- No schema change for MultiPolygons: the backend splits multi-part CSB polygons into separate fields,
  so `FieldSelection.geometry` stays a GeoJSON `Polygon`.

## 0.1.0

Initial contract.
