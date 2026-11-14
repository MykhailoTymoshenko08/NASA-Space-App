# backend/data

Generated files. Everything here except this README, `csb_ia_il_ne.pmtiles` and `plss.pmtiles` (both Git LFS) is gitignored. Rebuild with `make data` from `backend/`.

| File | Built by | Used by |
|---|---|---|
| `states.json`, `counties.json`, `states.parquet`, `counties.parquet` | `scripts/prepare_boundaries.py` | `/v1/geo/*`, county and US lookups |
| `places.json` | `scripts/prepare_boundaries.py` (Census 2020 incorporated places, field states only) | town label points in `boundaries.pmtiles` |
| `boundaries.pmtiles` (polygons `states`, `counties`; label points `state_labels`, `county_labels`, `places`; counties and towns only in the field states) | `scripts/prepare_boundaries.py` | `/v1/tiles/boundaries/...` |
| `plss.pmtiles` (polygons `townships`, `sections`; label points `township_labels`, `section_labels`; field states only), `plss_townships.parquet`, `plss_sections.parquet` (download cache) | `scripts/prepare_plss.py` (BLM PLSS + Census civil township names; needs `counties.parquet`) | `/v1/tiles/plss/...`. `plss.pmtiles` is **committed via Git LFS**; the parquet cache is not |
| `csb_ia_il_ne.pmtiles` (layer `fields`) | `scripts/prepare_csb.py tiles` (tippecanoe, from PostGIS) | `/v1/tiles/fields.pmtiles` (Range). **Committed via Git LFS** |
| `raw/csb/NationalCSB_2018-2025_rev23.zip` | `scripts/prepare_csb.py import` | download cache (3.76 GB); delete after import if disk is tight |

Field polygons and crop history are not files here: they live in PostGIS (`DATABASE_URL`), tables
`fields`, `field_crop_history`, `field_data_meta`.
