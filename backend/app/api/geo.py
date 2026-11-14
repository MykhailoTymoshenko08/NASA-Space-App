from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.core.config import FIELD_STATES
from app.core.errors import not_found
from app.models import County, State
from app.services import Services, get_services

router = APIRouter(tags=["geo"])

StateFipsParam = Annotated[str, Path(pattern=r"^[0-9]{2}$")]
CountyFipsParam = Annotated[str, Path(pattern=r"^[0-9]{5}$")]


@router.get("/geo/states")
def list_states(svc: Services = Depends(get_services)) -> dict[str, list[State]]:
    return {"items": svc.boundaries.field_states}


@router.get("/geo/states/{state_fips}/counties")
def list_counties(
    state_fips: StateFipsParam, svc: Services = Depends(get_services)
) -> dict[str, list[County]]:
    if state_fips not in FIELD_STATES or svc.boundaries.state(state_fips) is None:
        raise not_found(f"Unknown or unsupported state {state_fips}", state_fips=state_fips)
    return {"items": svc.boundaries.counties_of(state_fips)}


@router.get("/geo/counties/{county_fips}")
def get_county(county_fips: CountyFipsParam, svc: Services = Depends(get_services)) -> County:
    c = svc.boundaries.county(county_fips)
    if c is None:
        raise not_found(f"Unknown or unsupported county {county_fips}", county_fips=county_fips)
    return c
