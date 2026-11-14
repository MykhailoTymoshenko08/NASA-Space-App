from fastapi import APIRouter, Depends

from app.core.ratelimit import rate_limited
from app.geo.links import parse_input
from app.geo.resolve import resolve_point
from app.models import LatLon, LocationResolveRequest, ResolvedLocation, SelectionSource
from app.services import Services, get_services

router = APIRouter(tags=["geo"])


@router.post("/locations/resolve", dependencies=[Depends(rate_limited("locations"))])
async def resolve_location(
    body: LocationResolveRequest, svc: Services = Depends(get_services)
) -> ResolvedLocation:
    parsed = await parse_input(body.input, svc.link_client, svc.dns_resolver)
    point = LatLon(lat=parsed.point.lat, lon=parsed.point.lon)
    source = (
        SelectionSource.coordinates
        if parsed.kind == "plain_coordinates"
        else SelectionSource.location_link
    )
    selection = resolve_point(svc, point, source=source)
    return ResolvedLocation(input_kind=parsed.kind, point=point, selection=selection)
