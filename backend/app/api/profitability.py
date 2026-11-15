from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.core.ratelimit import rate_limited
from app.models import (
    ProfitCrop,
    ProfitEstimate,
    ProfitEstimateRequest,
    ProfitState,
    RotationBudget,
    RotationBudgetRequest,
)
from app.profitability import estimate_profit
from app.profitability.rotation import estimate_rotation_budget

router = APIRouter(tags=["profitability"], dependencies=[
    Depends(get_current_user), Depends(rate_limited("profitability")),
])


@router.post("/profitability/estimate")
def estimate(body: ProfitEstimateRequest) -> ProfitEstimate:
    return estimate_profit(body)


@router.post("/profitability/rotation")
def rotation(body: RotationBudgetRequest) -> RotationBudget:
    return estimate_rotation_budget(
        [s.model_dump() for s in body.sequence], body.state, body.area_ha,
        body.options, body.previous_crop, body.horizon_years,
    )


@router.get("/profitability/baselines")
def baselines() -> list[ProfitEstimate]:
    return [estimate_profit(ProfitEstimateRequest(crop=crop, state=state))
            for crop in ProfitCrop for state in ProfitState]
