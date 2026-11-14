"""XYZ vector tiles served from prebuilt PMTiles archives."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from app.geo.coverage import pilot_regions
from app.geo.tiles import TileSource, bbox_intersects, tile_bbox, valid_tile
from app.services import Services, get_services

router = APIRouter(tags=["tiles"])

MVT = "application/vnd.mapbox-vector-tile"
Z = Annotated[int, Path(ge=0, le=22)]
XY = Annotated[int, Path(ge=0)]


def _tile_response(src: TileSource | None, z: int, x: int, y: int) -> Response:
    if src is None or not valid_tile(z, x, y) or not (src.min_zoom <= z <= src.max_zoom):
        return Response(status_code=204)
    data = src.get(z, x, y)
    if not data:
        return Response(status_code=204)
    headers = {"Cache-Control": "public, max-age=86400"}
    if src.content_encoding:
        headers["Content-Encoding"] = src.content_encoding
    return Response(content=data, media_type=MVT, headers=headers)


@router.get("/tiles/fields/{z}/{x}/{y}.mvt")
def field_tile(z: Z, x: XY, y: XY, svc: Services = Depends(get_services)) -> Response:
    src = svc.field_tiles
    if src is None or z < svc.settings.field_tiles_min_zoom:
        return Response(status_code=204)
    if valid_tile(z, x, y):
        tb = tile_bbox(z, x, y)
        if not any(bbox_intersects(tb, r["bbox"]) for r in pilot_regions(svc)):
            return Response(status_code=204)
    return _tile_response(src, z, x, y)


@router.get("/tiles/boundaries/{z}/{x}/{y}.mvt")
def boundary_tile(z: Z, x: XY, y: XY, svc: Services = Depends(get_services)) -> Response:
    return _tile_response(svc.boundary_tiles, z, x, y)
