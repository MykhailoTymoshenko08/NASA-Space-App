"""USDA NRCS SSURGO via Soil Data Access (SDA): organic matter, pH, texture of the topsoil.

Docs: https://sdmdataaccess.sc.egov.usda.gov/WebServiceHelp.aspx
Table/column reference: https://www.nrcs.usda.gov/resources/data-and-reports/ssurgo/stats2go-metadata
Point lookup function SDA_Get_Mukey_from_intersection_with_WktWgs84 (WKT is "point(lon lat)").
Checked live 2026-11-14 with POST /Tabular/post.rest, format JSON+COLUMNNAME.

We take the dominant major component of the map unit at the field anchor and its surface horizon
(hzdept_r = 0). Values are survey "representative values" for that soil, not a lab test of this field.
"""

import httpx

from app.data_sources.base import MetricSpec
from app.models import LatLon, Metric, MetricCategory, MetricSource, Quality

URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

SRC = MetricSource(
    dataset="SSURGO (Soil Survey Geographic Database) via Soil Data Access",
    provider="USDA NRCS",
    url="https://sdmdataaccess.sc.egov.usda.gov/",
)
NOTE = (
    "Representative value for the dominant soil mapped at this spot (surface layer). "
    "Soil survey polygons, not a lab test of this field."
)

OM = MetricSpec("soil_organic_matter_pct", "Soil organic matter (topsoil)", MetricCategory.soil,
                "%", Quality.measured, SRC, None, NOTE)
PH = MetricSpec("soil_ph", "Soil pH (topsoil, 1:1 water)", MetricCategory.soil, "pH",
                Quality.measured, SRC, None, NOTE)
TEX = MetricSpec("soil_texture_class", "Soil texture (topsoil)", MetricCategory.soil, "class",
                 Quality.measured, SRC, None, NOTE)

QUERY = """
SELECT TOP 1 mu.mukey, mu.muname, c.compname, c.comppct_r, ch.hzdepb_r,
       ch.om_r, ch.ph1to1h2o_r, tg.texdesc
FROM mapunit mu
INNER JOIN component c ON c.mukey = mu.mukey AND c.majcompflag = 'Yes'
INNER JOIN chorizon ch ON ch.cokey = c.cokey AND ch.hzdept_r = 0
LEFT JOIN chtexturegrp tg ON tg.chkey = ch.chkey AND tg.rvindicator = 'Yes'
WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon} {lat})'))
ORDER BY c.comppct_r DESC
"""


def _num(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


class SsurgoSource:
    name = "ssurgo"
    specs = [OM, PH, TEX]

    async def fetch(self, client: httpx.AsyncClient, anchor: LatLon) -> list[Metric]:
        # Floats are formatted by us, never user strings: no injection surface.
        q = QUERY.format(lon=f"{float(anchor.lon):.6f}", lat=f"{float(anchor.lat):.6f}")
        r = await client.post(URL, json={"query": q, "format": "JSON+COLUMNNAME"})
        r.raise_for_status()
        table = (r.json() or {}).get("Table") or []
        if len(table) < 2:
            reason = "No soil survey data at this point (water, urban area, or unmapped)."
            return [s.unavailable(reason) for s in self.specs]
        row = dict(zip(table[0], table[1], strict=False))
        depth = _num(row.get("hzdepb_r"))
        note = f"{NOTE} Soil: {row.get('compname')} ({row.get('comppct_r')}% of map unit)" + (
            f", surface layer 0-{int(depth)} cm." if depth else "."
        )
        om, ph, tex = _num(row.get("om_r")), _num(row.get("ph1to1h2o_r")), row.get("texdesc")
        return [
            OM.metric(om, note=note),
            PH.metric(ph, note=note),
            TEX.metric(tex or None, note=note),
        ]
