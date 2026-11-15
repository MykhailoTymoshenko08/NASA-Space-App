import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.analyses.service import job_json
from app.core.errors import ApiException, ErrorCode, not_found
from app.core.ratelimit import rate_limited
from app.geo.resolve import resolve_ref
from app.models import AnalysisRequest, JobStatus
from app.report.render import report_pdf
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


@router.get("/analyses/{job_id}/report.pdf", dependencies=[Depends(rate_limited("reports"))])
def get_analysis_report(job_id: str, svc: Services = Depends(get_services)) -> Response:
    """The finished analysis as a printable A4 PDF. Sync on purpose: rendering runs in the threadpool."""
    rec = svc.analyses.record(job_id.lower())
    if rec is None:
        raise not_found(f"Unknown analysis job {job_id}", job_id=job_id)
    job = rec.job
    if job.status != JobStatus.succeeded or job.result is None:
        raise ApiException(
            ErrorCode.ANALYSIS_NOT_READY,
            "The report is ready once the analysis has finished."
            if job.status != JobStatus.failed
            else "This analysis failed, so it has no report. Please run it again.",
            {"status": job.status.value},
        )
    if rec.report_pdf is None:
        # A finished job never changes: render once, then serve the same bytes.
        rec.report_pdf = report_pdf(job.result, rec.options, job.job_id)
    county = job.result.selection.county
    # ASCII slug only: county names can hold quotes or accents (O'Brien County, IA).
    slug = re.sub(r"[^a-z0-9]+", "-", f"{county.name} {county.state_postal}".lower()).strip("-")
    name = f"seloai-analysis-{slug}-{job.job_id[:8]}"
    return Response(
        rec.report_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.pdf"',
            "Cache-Control": "private, max-age=3600",
        },
    )
