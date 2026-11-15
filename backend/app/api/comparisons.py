"""Field comparisons for signed-in farmers: 2-4 saved fields side by side, and rankings of a whole area."""

from fastapi import APIRouter, Depends

from app.api.saved_fields import get_saved_field_store
from app.auth.deps import get_current_user
from app.auth.store import User
from app.comparisons.saved import compare_saved_fields
from app.core.errors import ApiException, ErrorCode
from app.core.ratelimit import rate_limited
from app.models import AreaRanking, AreaRankingRequest, FieldComparison, SavedFieldComparisonRequest
from app.saved_fields.store import SavedFieldStore
from app.services import Services, get_services

router = APIRouter(tags=["comparisons"])


@router.post("/comparisons/saved-fields", dependencies=[Depends(rate_limited("comparisons"))])
async def compare_saved(
    body: SavedFieldComparisonRequest,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
    svc: Services = Depends(get_services),
) -> FieldComparison:
    return await compare_saved_fields(svc, store, user.id, body)


@router.post("/comparisons/area", dependencies=[Depends(rate_limited("comparisons"))])
async def rank_area(
    body: AreaRankingRequest,
    user: User = Depends(get_current_user),
    svc: Services = Depends(get_services),
) -> AreaRanking:
    if svc.area_rankings is None:
        raise ApiException(ErrorCode.INTERNAL_ERROR,
                           "Field rankings are unavailable (field database not reachable).")
    return await svc.area_rankings.rank(svc, body)
