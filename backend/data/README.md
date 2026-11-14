# backend/data

Generated files. Everything here except this README is gitignored. Rebuild with `make data` from `backend/`.

| File | Built by | Used by |
|---|---|---|
| `states.json`, `counties.json`, `states.parquet`, `counties.parquet` | `scripts/prepare_boundaries.py` | `/v1/geo/*`, county and US lookups |
| `boundaries.pmtiles` (`states`, `counties`) | `scripts/prepare_boundaries.py` | `/v1/tiles/boundaries/...` |
| `csb_ia_il_ne.pmtiles` (layer `fields`) | `scripts/prepare_csb.py tiles` (tippecanoe, from PostGIS) | frontend, via static hosting (`FIELDS_PMTILES_URL`); not served by the backend |
| `raw/csb/NationalCSB_2018-2025_rev23.zip` | `scripts/prepare_csb.py import` | download cache (3.76 GB); delete after import if disk is tight |

Field polygons and crop history are not files here: they live in PostGIS (`DATABASE_URL`), tables
`fields`, `field_crop_history`, `field_data_meta`.
