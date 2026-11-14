"""USDA NRCS SSURGO via Soil Data Access (SDA): organic matter, pH, texture of the topsoil.

Docs: https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx
Spatial macros (~DeclareGeometry~, ~GetClippedMapunits~): https://sdmdataaccess.nrcs.usda.gov/documents/
Table/column reference: https://www.nrcs.usda.gov/resources/data-and-reports/ssurgo/stats2go-metadata
Checked live 2026-11-14 with POST /Tabular/post.rest, format JSON+COLUMNNAME (~2 s per field area).

For an estimated CSB field area we clip the soil map units to the polygon and area-weight the dominant
major component of each map unit (surface horizon, hzdept_r = 0): organic matter and pH are
area-weighted means, texture is the class covering the largest area. If that query fails or returns
nothing (or the selection is a buffered point) we sample the map unit at the anchor point and say so
in the metric note. Values are survey "representative values", not a lab test of this land.
"""

import logging

import httpx
import shapely
from shapely.geometry import shape

from app.data_sources.base import MetricSpec
from app.models import BoundaryType, FieldSelection, Metric, MetricCategory, MetricSource, Quality

log = logging.getLogger(__name__)

URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SIMPLIFY_DEG = 0.00005  # ~5 m: keeps the WKT short, area weights unchanged in practice

SRC = MetricSource(
    dataset="SSURGO (Soil Survey Geographic Database) via Soil Data Access",
    provider="USDA NRCS",
    url="https://sdmdataaccess.sc.egov.usda.gov/",
)
BASE_NOTE = "Soil survey representative values for the surface layer, not a lab test of this land."

OM = MetricSpec("soil_organic_matter_pct", "Soil organic matter (topsoil)", MetricCategory.soil,
                "%", Quality.measured, SRC, None, BASE_NOTE)
PH = MetricSpec("soil_ph", "Soil pH (topsoil, 1:1 water)", MetricCategory.soil, "pH",
                Quality.measured, SRC, None, BASE_NOTE)
TEX = MetricSpec("soil_texture_class", "Soil texture (topsoil)", MetricCategory.soil, "class",
                 Quality.measured, SRC, None, BASE_NOTE)

# Dominant major component of a map unit, surface horizon. Values joined with '|' (NULL -> '').
_DOMINANT = """(SELECT TOP 1 CONCAT(c.compname, '|', c.comppct_r, '|', ch.om_r, '|', ch.ph1to1h2o_r, '|',
        tg.texdesc)
   FROM component c
   INNER JOIN chorizon ch ON ch.cokey = c.cokey AND ch.hzdept_r = 0
   LEFT JOIN chtexturegrp tg ON tg.chkey = ch.chkey AND tg.rvindicator = 'Yes'
   WHERE c.mukey = mu.mukey AND c.majcompflag = 'Yes'
   ORDER BY c.comppct_r DESC)"""

AREA_QUERY = """~DeclareGeometry(@aoi)~
select @aoi = geometry::STPolyFromText('{wkt}', 4326)
~DeclareIdGeomTable(@clipped)~
~GetClippedMapunits(@aoi,polygon,geo,@clipped)~
SELECT mu.mukey, SUM(t.geom.STArea()) AS area, """ + _DOMINANT + """ AS dom
FROM @clipped t INNER JOIN mapunit mu ON mu.mukey = t.id
GROUP BY mu.mukey
"""

POINT_QUERY = """SELECT TOP 1 mu.mukey, 1 AS area, """ + _DOMINANT + """ AS dom
FROM mapunit mu
WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
"""


def _num(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _rows(payload) -> list[dict]:
    table = (payload or {}).get("Table") or []
    if len(table) < 2:
        return []
    return [dict(zip(table[0], r, strict=False)) for r in table[1:]]


def summarise(rows: list[dict]) -> dict:
    """Area-weighted summary over map units. Each row: mukey, area, dom='name|pct|om|ph|texture'."""
    om_w = om_s = ph_w = ph_s = 0.0
    tex_area: dict[str, float] = {}
    names: dict[str, float] = {}
    for r in rows:
        a = _num(r.get("area")) or 0.0
        parts = (str(r.get("dom") or "").split("|") + [""] * 5)[:5]
        name, _pct, om, ph, tex = parts
        if a <= 0:
            continue
        if (v := _num(om)) is not None:
            om_s += v * a
            om_w += a
        if (v := _num(ph)) is not None:
            ph_s += v * a
            ph_w += a
        if tex:
            tex_area[tex] = tex_area.get(tex, 0) + a
        if name:
            names[name] = names.get(name, 0) + a
    total = sum(_num(r.get("area")) or 0 for r in rows)
    main = max(names, key=names.get) if names else None
    return {
        "om": round(om_s / om_w, 1) if om_w else None,
        "ph": round(ph_s / ph_w, 1) if ph_w else None,
        "texture": max(tex_area, key=tex_area.get) if tex_area else None,
        "units": len(rows),
        "main_soil": main,
        "main_share": round(100 * names[main] / total) if main and total else None,
    }


class SsurgoSource:
    name = "ssurgo"
    specs = [OM, PH, TEX]

    async def _query(self, client: httpx.AsyncClient, q: str) -> list[dict]:
        r = await client.post(URL, json={"query": q, "format": "JSON+COLUMNNAME"})
        r.raise_for_status()
        return _rows(r.json())

    async def fetch(self, client: httpx.AsyncClient, selection: FieldSelection) -> list[Metric]:
        rows: list[dict] = []
        mode = "point"
        fallback_reason = ""
        if selection.boundary_type == BoundaryType.estimated_csb:
            try:
                poly = shapely.simplify(shape(selection.geometry.model_dump()), SIMPLIFY_DEG)
                # WKT is built from our own polygon (numbers only): no injection surface.
                rows = await self._query(client, AREA_QUERY.format(
                    wkt=shapely.to_wkt(poly, rounding_precision=6)))
                mode = "area" if rows else "point"
                if not rows:
                    fallback_reason = "the field-area query returned no soil map units"
            except Exception as e:  # noqa: BLE001 - fall back to the point query
                log.info("SSURGO area query failed, using anchor point: %r", e)
                fallback_reason = "the area-weighted query failed"
        if not rows:
            a = selection.anchor
            rows = await self._query(
                client, POINT_QUERY.format(lon=f"{float(a.lon):.6f}", lat=f"{float(a.lat):.6f}"))
        if not rows:
            reason = "No soil survey data here (water, urban area, or unmapped)."
            return [s.unavailable(reason) for s in self.specs]

        s = summarise(rows)
        if mode == "area":
            note = (f"Area-weighted over the estimated field area ({s['units']} soil map units; "
                    f"main soil {s['main_soil']}, about {s['main_share']}% of the area). {BASE_NOTE}")
        else:
            where = "the field area's anchor point" if selection.boundary_type == BoundaryType.estimated_csb \
                else "the selected point"
            why = f" because {fallback_reason}" if fallback_reason else ""
            note = f"Sampled at {where}{why} (soil: {s['main_soil']}). {BASE_NOTE}"
        return [
            OM.metric(s["om"], note=note),
            PH.metric(s["ph"], note=note),
            TEX.metric(s["texture"], note=note),
        ]
