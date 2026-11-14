"""ISRIC SoilGrids 2.0: total nitrogen in the top 0-5 cm (stretch metric, estimated).

Docs: https://rest.isric.org/soilgrids/v2.0/docs
Checked live 2026-11-14: GET /soilgrids/v2.0/properties/query?lon&lat&property=nitrogen&depth=0-5cm
&value=mean returns mapped units cg/kg with d_factor 100 (value / 100 = g/kg). `mean` is null where
there is no prediction (urban, water). The service is known to be flaky; any failure -> unavailable.
NASA does not measure soil nitrogen; this is a machine-learning estimate, not organic matter.
"""

import httpx

from app.data_sources.base import MetricSpec
from app.models import LatLon, Metric, MetricCategory, MetricSource, Quality

URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
SRC = MetricSource(dataset="SoilGrids 2.0 (nitrogen, 0-5 cm)", provider="ISRIC",
                   url="https://soilgrids.org/")
SPEC = MetricSpec(
    "soil_nitrogen_total", "Total soil nitrogen (estimated, 0-5 cm)", MetricCategory.soil, "g/kg",
    Quality.estimated, SRC, 250.0,
    "Machine-learning estimate from global soil samples at 250 m, not a field measurement. "
    "Not plant-available nitrogen; a soil test is needed for fertilizer decisions.",
)


class SoilGridsSource:
    name = "soilgrids"
    specs = [SPEC]

    async def fetch(self, client: httpx.AsyncClient, anchor: LatLon) -> list[Metric]:
        r = await client.get(
            URL,
            params={"lon": anchor.lon, "lat": anchor.lat, "property": "nitrogen",
                    "depth": "0-5cm", "value": "mean"},
        )
        r.raise_for_status()
        layers = r.json()["properties"]["layers"]
        layer = next(lyr for lyr in layers if lyr["name"] == "nitrogen")
        d_factor = layer.get("unit_measure", {}).get("d_factor") or 100
        mean = layer["depths"][0]["values"].get("mean")
        if mean is None:
            return [SPEC.unavailable("SoilGrids has no prediction here (often urban or water areas).")]
        return [SPEC.metric(round(mean / d_factor, 2))]
