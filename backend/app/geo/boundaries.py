"""States and counties prepared by scripts/prepare_boundaries.py."""

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely import STRtree

from app.geo.crs import to_5070
from app.models import County, CountyRef, State

COUNTY_FIELDS = set(County.model_fields)


class DataMissing(RuntimeError):
    """A prepared data file is missing. Run `make data`."""


def _read_json(path: Path):
    if not path.exists():
        raise DataMissing(f"{path} not found; run `make data`")
    return json.loads(path.read_text())


@dataclass
class Boundaries:
    states: list[State]
    counties: list[County]
    _county_geoms_5070: np.ndarray
    _county_fips: list[str]
    _tree: STRtree
    _state_tree: STRtree

    @classmethod
    def load(cls, data_dir: Path, pilot_counties: list[str]) -> "Boundaries":
        states = [State(**s) for s in _read_json(data_dir / "states.json")]
        pilot = set(pilot_counties)
        counties = []
        for c in _read_json(data_dir / "counties.json"):
            rec = {k: v for k, v in c.items() if k in COUNTY_FIELDS}
            # Coverage follows the current PILOT_REGION, not what was baked in at build time.
            rec["has_field_coverage"] = rec["fips"] in pilot
            counties.append(County(**rec))
        pq = data_dir / "counties.parquet"
        if not pq.exists():
            raise DataMissing(f"{pq} not found; run `make data`")
        gdf = gpd.read_parquet(pq)
        geoms = to_5070(gdf.geometry.values)
        spq = data_dir / "states.parquet"
        if not spq.exists():
            raise DataMissing(f"{spq} not found; run `make data`")
        state_geoms = to_5070(gpd.read_parquet(spq).geometry.values)
        return cls(
            states, counties, geoms, list(gdf["fips"]), STRtree(geoms), STRtree(state_geoms)
        )

    def __post_init__(self) -> None:
        self._states_by_fips = {s.fips: s for s in self.states}
        self._states_by_postal = {s.postal: s for s in self.states}
        self._counties_by_fips = {c.fips: c for c in self.counties}

    def state(self, fips: str) -> State | None:
        return self._states_by_fips.get(fips)

    def county(self, fips: str) -> County | None:
        return self._counties_by_fips.get(fips)

    def counties_of(self, state_fips: str) -> list[County]:
        return sorted(
            (c for c in self.counties if c.state_fips == state_fips), key=lambda c: c.name
        )

    def in_us(self, x: float, y: float, tolerance_m: float = 2000) -> bool:
        """True if the EPSG:5070 point is in (or within `tolerance_m` of) a CONUS state.

        The tolerance absorbs the ~200 m generalisation of the prepared outlines at coastlines.
        """
        hits = self._state_tree.query(shapely.Point(x, y), predicate="dwithin", distance=tolerance_m)
        return len(hits) > 0

    def county_at(self, x: float, y: float) -> County | None:
        """County containing the EPSG:5070 point (x, y), else the nearest one."""
        pt = shapely.Point(x, y)
        hits = self._tree.query(pt, predicate="intersects")
        if len(hits) == 0:
            hits = self._tree.query_nearest(pt, max_distance=50_000)
        if len(hits) == 0:
            return None
        return self._counties_by_fips.get(self._county_fips[int(hits[0])])

    @staticmethod
    def ref(c: County) -> CountyRef:
        return CountyRef(fips=c.fips, name=c.name, state_postal=c.state_postal)
