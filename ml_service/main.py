"""FastAPI app. run: uvicorn ml_service.main:app --reload --port 8001

ML_MODE=real (default) answers with the real analysis; ML_MODE=mock keeps the contract-shaped mock.
The mode is read on every request, so it can be switched without a restart in tests.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import COVERAGE_STATES, COVERAGE_YEARS, MODEL_VERSION
from . import crops as crop_db
from .analyze import run_analysis
from .errors import ApiError, ErrorResponse, error_payload
from .schemas import AnalyzeRequest, AnalyzeResponse, CropsResponse, HealthResponse

log = logging.getLogger("ml_service")


def mode() -> str:
    return "mock" if os.environ.get("ML_MODE", "real").lower() == "mock" else "real"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if mode() == "real":          # load the model and tables once, so the first request is as fast as the others
        from . import real
        real.warm_up()
    yield


app = FastAPI(title="FieldShift ML service", version="0.2.0", lifespan=lifespan,
              description="docs/api_contract.md (v1). ML_MODE=real (default) or ML_MODE=mock")

# the frontend never calls ML directly, but CORS stays open for local demos and swagger
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_ERRORS = {422: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
           503: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse(error_payload(exc.code, exc.message, exc.details), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # keep only json-safe parts of the pydantic errors
    errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    first = errors[0] if errors else {"loc": [], "msg": "invalid request"}
    message = f"{'.'.join(first['loc'])}: {first['msg']}" if first["loc"] else first["msg"]
    return JSONResponse(error_payload("INVALID_INPUT", message, {"errors": errors}), status_code=422)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "INTERNAL")
    return JSONResponse(error_payload(code, str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(error_payload("INTERNAL", "Internal error.", {}), status_code=500)


@app.get("/ml/health", response_model=HealthResponse, response_model_exclude_unset=True)
def health():
    version = MODEL_VERSION
    if mode() == "real":
        from .real import MODEL_VERSION_REAL
        version = MODEL_VERSION_REAL
    return {"status": "ok", "model_version": version, "mode": mode(),
            "coverage": {"states": list(COVERAGE_STATES), "years": list(COVERAGE_YEARS)}}


@app.get("/ml/v1/meta/crops", response_model=CropsResponse)
def crops():
    if mode() == "mock":
        return {"crops": [
            {"crop": c.slug, "cdl_code": c.cdl_code, "name_en": c.name_en, "name_uk": c.name_uk, "type": c.type}
            for c in crop_db.CATALOG.values()
        ]}
    from .feature_text import CROP_NAMES
    from .real import assets
    a = assets()
    return {"crops": [
        {"crop": slug, "cdl_code": info["cdl_code"], "name_en": CROP_NAMES[slug][0], "name_uk": CROP_NAMES[slug][1],
         "type": a.rules["crops"][slug]["type"]}
        for slug, info in a.candidates.items()
    ]}


@app.post("/ml/v1/analyze", response_model=AnalyzeResponse, response_model_exclude_unset=True, responses=_ERRORS)
def analyze(req: AnalyzeRequest):
    if mode() == "mock":
        return run_analysis(req)
    from .real import analyze_real
    return analyze_real(req)
