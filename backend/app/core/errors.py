"""Error envelope (`ErrorResponse`) and the ErrorCode -> HTTP status mapping."""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNPARSEABLE_INPUT = "UNPARSEABLE_INPUT"
    UNSUPPORTED_LINK = "UNSUPPORTED_LINK"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    UPSTREAM_DATA_UNAVAILABLE = "UPSTREAM_DATA_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    EMAIL_TAKEN = "EMAIL_TAKEN"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.EMAIL_TAKEN: 409,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.UNPARSEABLE_INPUT: 422,
    ErrorCode.UNSUPPORTED_LINK: 422,
    ErrorCode.OUTSIDE_COVERAGE: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_DATA_UNAVAILABLE: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ApiException(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}

    @property
    def status_code(self) -> int:
        return HTTP_STATUS[self.code]


def not_found(message: str, **details: Any) -> ApiException:
    return ApiException(ErrorCode.NOT_FOUND, message, details or None)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def error_body(
    code: ErrorCode, message: str, request_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code.value, "message": message, "request_id": request_id}
    if details:
        err["details"] = details
    return {"error": err}


def error_response(
    request: Request,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = request_id_of(request)
    hdrs = {"X-Request-Id": rid, **(headers or {})}
    return JSONResponse(
        error_body(code, message, rid, details), status_code=HTTP_STATUS[code], headers=hdrs
    )


def _loc(loc: tuple | list) -> str:
    # Drop the "body"/"path"/"query" prefix: the frontend wants the field name.
    parts = [str(p) for p in loc]
    if parts and parts[0] in {"body", "path", "query", "header"}:
        parts = parts[1:]
    return ".".join(parts)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(request: Request, exc: ApiException) -> JSONResponse:
        return error_response(request, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": _loc(e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()
        ]
        first = errors[0] if errors else {"field": "", "message": "Invalid request"}
        msg = f"Invalid request: {first['field'] or 'body'}: {first['message']}"
        return error_response(
            request,
            ErrorCode.VALIDATION_ERROR,
            msg,
            {"field": first["field"], "errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return error_response(request, ErrorCode.NOT_FOUND, "Not found")
        if exc.status_code == 405:
            rid = request_id_of(request)
            return JSONResponse(
                error_body(ErrorCode.VALIDATION_ERROR, "Method not allowed", rid),
                status_code=405,
                headers={"X-Request-Id": rid},
            )
        if exc.status_code >= 500:
            return error_response(request, ErrorCode.INTERNAL_ERROR, "Internal error")
        return error_response(request, ErrorCode.VALIDATION_ERROR, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": request_id_of(request)})
        return error_response(request, ErrorCode.INTERNAL_ERROR, "Internal error")
