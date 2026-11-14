from fastapi import APIRouter, Depends, Request

from app.geo.coverage import build_coverage
from app.models import Coverage
from app.services import Services, get_services

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta/coverage", response_model=Coverage, response_model_exclude_none=True)
def coverage(request: Request, svc: Services = Depends(get_services)) -> Coverage:
    # Absolute URL of the backend-served file (honours X-Forwarded-* with uvicorn --proxy-headers),
    # unless FIELDS_PMTILES_URL points at external hosting.
    url = svc.settings.fields_pmtiles_url or str(request.url_for("fields_pmtiles"))
    return build_coverage(svc, url)
