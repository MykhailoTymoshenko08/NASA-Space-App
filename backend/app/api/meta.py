from fastapi import APIRouter, Depends

from app.geo.coverage import build_coverage
from app.models import Coverage
from app.services import Services, get_services

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta/coverage", response_model=Coverage, response_model_exclude_none=True)
def coverage(svc: Services = Depends(get_services)) -> Coverage:
    return build_coverage(svc)
