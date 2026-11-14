from fastapi import APIRouter

from app.models import ProfitEstimate, ProfitEstimateRequest
from app.profitability import estimate_profit

router = APIRouter(tags=["profitability"])


# TODO(auth): add dependencies=[Depends(get_current_user)] when field endpoints require sign-in.
@router.post("/profitability/estimate")
def estimate(body: ProfitEstimateRequest) -> ProfitEstimate:
    return estimate_profit(body)
