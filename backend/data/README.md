# backend/data

Generated files. Everything here except this README is gitignored. Rebuild with `make data` from `backend/`.

| File | Built by | Used by |
|---|---|---|
| `states.json`, `counties.json` | `scripts/prepare_boundaries.py` | `/v1/geo/*`, county lookup |
| `counties.parquet` | `scripts/prepare_boundaries.py` | point-in-county lookup |
| `boundaries.pmtiles` | `scripts/prepare_boundaries.py` (tippecanoe) | `/v1/tiles/boundaries/...` |
| `fields.parquet`, `fields_meta.json` | `scripts/prepare_field_data.py` | `/v1/fields/*`, point resolution, coverage |
| `fields.pmtiles` | `scripts/prepare_field_data.py` (tippecanoe) | `/v1/tiles/fields/...` |
