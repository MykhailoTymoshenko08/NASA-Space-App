"""Soil at many field points in two SDA requests per batch: point -> map unit, then map unit -> rating.

Used to rate every field of a county or township for ranking. One point per field (inside the polygon),
so it is a screening value; the side-by-side comparison uses the area-weighted snapshot instead.
Checked live 2026-11-15: 500 points take about 6 s, the map-unit query under 1 s.
"""

import httpx

from app.data_sources.ssurgo import NCCPI_RULE, URL, _rows

BATCH_SIZE = 400
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

_POINTS = """SELECT p.id, m.mukey FROM (VALUES {values}) p(id, wkt)
CROSS APPLY SDA_Get_Mukey_from_intersection_with_WktWgs84(p.wkt) m"""

_UNITS = """SELECT mu.mukey,
  (SELECT SUM(c.comppct_r * ci.interphr)
          / NULLIF(SUM(CASE WHEN ci.interphr IS NOT NULL THEN c.comppct_r END), 0)
     FROM component c
     LEFT JOIN cointerp ci ON ci.cokey = c.cokey AND ci.ruledepth = 0
       AND ci.mrulename = '""" + NCCPI_RULE + """'
     WHERE c.mukey = mu.mukey AND c.majcompflag = 'Yes') AS nccpi,
  (SELECT TOP 1 c.compname FROM component c WHERE c.mukey = mu.mukey ORDER BY c.comppct_r DESC, c.cokey)
     AS soil_name,
  (SELECT TOP 1 c.drainagecl FROM component c WHERE c.mukey = mu.mukey ORDER BY c.comppct_r DESC, c.cokey)
     AS drainage
FROM mapunit mu WHERE mu.mukey IN ({keys})"""


async def _query(client: httpx.AsyncClient, q: str) -> list[dict]:
    r = await client.post(URL, json={"query": q, "format": "JSON+COLUMNNAME"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return _rows(r.json())


def _text(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


async def fetch_point_soils(
    client: httpx.AsyncClient, points: list[tuple[str, float, float]],
) -> dict[str, dict]:
    """`points`: (field_id, lon, lat), at most BATCH_SIZE. Returns field_id -> {mukey, nccpi (0-100),
    soil_name, drainage}; every field id is present, with all None where the survey has no map unit."""
    if not points:
        return {}
    if len(points) > BATCH_SIZE:
        raise ValueError(f"at most {BATCH_SIZE} points per batch")
    # Only our own numbers go into the SQL: list indexes and formatted floats.
    values = ",".join(f"({i},'point({lon:.6f} {lat:.6f})')" for i, (_, lon, lat) in enumerate(points))
    mukey_of: dict[int, str] = {}
    for row in await _query(client, _POINTS.format(values=values)):
        idx, mukey = int(row["id"]), str(row.get("mukey") or "")
        if mukey.isdigit():
            mukey_of.setdefault(idx, mukey)
    units: dict[str, dict] = {}
    keys = sorted(set(mukey_of.values()))
    if keys:
        for row in await _query(client, _UNITS.format(keys=",".join(f"'{k}'" for k in keys))):
            raw = row.get("nccpi")
            try:
                nccpi = round(100 * float(raw), 1) if raw not in (None, "") else None
            except (TypeError, ValueError):
                nccpi = None
            units[str(row["mukey"])] = {
                "nccpi": nccpi, "soil_name": _text(row.get("soil_name")),
                "drainage": _text(row.get("drainage")),
            }
    out = {}
    for i, (field_id, _, _) in enumerate(points):
        mukey = mukey_of.get(i)
        unit = units.get(mukey or "", {})
        out[field_id] = {"mukey": mukey, "nccpi": unit.get("nccpi"), "soil_name": unit.get("soil_name"),
                         "drainage": unit.get("drainage")}
    return out
