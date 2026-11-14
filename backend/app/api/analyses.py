from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.analyses.service import job_json
from app.core.errors import not_found
from app.core.ratelimit import rate_limited
from app.geo.resolve import resolve_ref
from app.models import AnalysisRequest
from app.services import Services, get_services

router = APIRouter(tags=["analyses"])

@router.post("/analyses", status_code=202, dependencies=[Depends(rate_limited("analyses"))])
async def create_analysis(body: AnalysisRequest, svc: Services = Depends(get_services)) -> JSONResponse:
    selection = resolve_ref(svc, body.selection)
    job = svc.analyses.create(selection, body.options)
    return JSONResponse(
        job_json(job), status_code=202, headers={"Location": f"/v1/analyses/{job.job_id}"}
    )


@router.get("/analyses/{job_id}")
def get_analysis(job_id: str, svc: Services = Depends(get_services)) -> JSONResponse:
    # Any unknown or malformed id is a 404: the contract describes no 422 here.
    job = svc.analyses.get(job_id.lower())
    if job is None:
        raise not_found(f"Unknown analysis job {job_id}", job_id=job_id)
    return JSONResponse(job_json(job))
