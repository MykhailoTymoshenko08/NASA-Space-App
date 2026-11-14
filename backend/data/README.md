# backend/data

Generated files. Everything here except this README is gitignored. Rebuild with `make data` from `backend/`.

| File | Built by | Used by |
|---|---|---|
| `states.json`, `counties.json`, `states.parquet`, `counties.parquet` | `scripts/prepare_boundaries.py` | `/v1/geo/*`, county and US lookups |
| `sections.parquet`, `townships.parquet`, `plss_meta.json` | `scripts/prepare_plss.py` | `/v1/fields/*`, point resolution, coverage |
| `fields.pmtiles` (layer `fields` = PLSS sections) | `scripts/prepare_plss.py` (tippecanoe) | `/v1/tiles/fields/...` |
| `boundaries.pmtiles` (`states`, `counties`, `townships`) | `scripts/prepare_boundaries.py`, rebuilt by `prepare_plss.py` | `/v1/tiles/boundaries/...` |
| `raw/plss/<STATE>/` | `scripts/prepare_plss.py` | download cache (BLM pages), safe to delete |
