from fastapi import APIRouter, Depends

from app.geo.resolve import get_field_selection, resolve_point
from app.models import FieldInfo, FieldResolveRequest, FieldSelection, PointRef, SelectionSource
from app.services import Services, get_services

router = APIRouter(tags=["fields"])


# TODO(auth): add dependencies=[Depends(get_current_user)] when auth is merged.
@router.post("/fields/info")
async def field_info(body: PointRef, svc: Services = Depends(get_services)) -> FieldInfo:
    return await svc.field_info.info(body.point)


@router.post("/fields/resolve")
def resolve_field(body: FieldResolveRequest, svc: Services = Depends(get_services)) -> FieldSelection:
    return resolve_point(
        svc, body.point, body.snap_radius_m, body.source or SelectionSource.map_click
    )


@router.get("/fields/{field_id}")
def get_field(field_id: str, svc: Services = Depends(get_services)) -> FieldSelection:
    return get_field_selection(svc, field_id, SelectionSource.landing_map_click)
