"""In-memory spatial index over data/fields.parquet (built by scripts/prepare_field_data.py).

Expected columns: field_id, crop_class, area_ha, county_fips, crop_history (JSON string,
newest first), geometry (Polygon, EPSG:4326).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely import STRtree

from app.geo.crs import to_5070


@dataclass(frozen=True)
class FieldRecord:
    field_id: str
    crop_class: str
    area_ha: float
    county_fips: str
    crop_history: list[dict]
    geometry: shapely.Polygon  # EPSG:4326
    geometry_5070: shapely.Polygon


class FieldIndex:
    def __init__(self, gdf: gpd.GeoDataFrame):
        self._gdf = gdf.reset_index(drop=True)
        self._geoms = np.asarray(self._gdf.geometry.values)
        self._geoms_5070 = to_5070(self._geoms)
        self._tree = STRtree(self._geoms_5070)
        self._by_id = {fid: i for i, fid in enumerate(self._gdf["field_id"])}

    @classmethod
    def load(cls, path: Path) -> "FieldIndex":
        gdf = gpd.read_parquet(path)
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        return cls(gdf)

    def __len__(self) -> int:
        return len(self._gdf)

    def _record(self, i: int) -> FieldRecord:
        row = self._gdf.iloc[i]
        hist = row.get("crop_history")
        return FieldRecord(
            field_id=row["field_id"],
            crop_class=row.get("crop_class") or "",
            area_ha=float(row["area_ha"]),
            county_fips=row.get("county_fips") or "",
            crop_history=json.loads(hist) if isinstance(hist, str) and hist else [],
            geometry=self._geoms[i],
            geometry_5070=self._geoms_5070[i],
        )

    def get(self, field_id: str) -> FieldRecord | None:
        i = self._by_id.get(field_id)
        return None if i is None else self._record(i)

    def containing(self, x: float, y: float) -> FieldRecord | None:
        """Field polygon containing the EPSG:5070 point. Smallest wins if polygons overlap."""
        hits = self._tree.query(shapely.Point(x, y), predicate="intersects")
        if len(hits) == 0:
            return None
        i = min(hits, key=lambda h: self._geoms_5070[h].area)
        return self._record(int(i))

    def nearest(self, x: float, y: float, max_distance_m: float) -> tuple[FieldRecord, float] | None:
        if max_distance_m <= 0:
            return None
        pt = shapely.Point(x, y)
        idx, dist = self._tree.query_nearest(pt, max_distance=max_distance_m, return_distance=True)
        if len(idx) == 0:
            return None
        return self._record(int(idx[0])), float(dist[0])
