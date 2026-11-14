"""Vector tiles.

- Boundaries (states, counties): XYZ tiles read out of a prebuilt PMTiles archive.
- Field polygons: the whole PMTiles file, served as a static file with HTTP Range support; the frontend
  reads it with the PMTiles client (`pmtiles://` protocol), never as XYZ tiles.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import FileResponse

from app.core.errors import not_found
from app.geo.tiles import TileSource, valid_tile
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


@router.api_route("/tiles/fields.pmtiles", methods=["GET", "HEAD"], name="fields_pmtiles")
def fields_pmtiles(svc: Services = Depends(get_services)) -> Response:
    # FileResponse answers `Range: bytes=a-b` with 206 + Content-Range (416 when unsatisfiable) and sets
    # ETag/Last-Modified from the file, which PMTiles clients use to detect a changed archive.
    path = svc.settings.data_dir / svc.settings.fields_pmtiles_file
    if not path.is_file():
        raise not_found("Field tiles are not prepared on this server (run `make data-tiles`).")
    return FileResponse(
        path, media_type="application/vnd.pmtiles", headers={"Cache-Control": "public, max-age=3600"}
    )


@router.get("/tiles/boundaries/{z}/{x}/{y}.mvt")
def boundary_tile(z: Z, x: XY, y: XY, svc: Services = Depends(get_services)) -> Response:
    return _tile_response(svc.boundary_tiles, z, x, y)
