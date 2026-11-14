"""Error type and codes from the api contract ({"error": {code, message, details}})."""
from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """raised anywhere in the service, turned into the contract error json by the handler"""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def invalid_input(message: str, **details: Any) -> ApiError:
    return ApiError(422, "INVALID_INPUT", message, details)


def out_of_coverage(message: str, **details: Any) -> ApiError:
    return ApiError(404, "OUT_OF_COVERAGE", message, details)


def data_unavailable(message: str, **details: Any) -> ApiError:
    return ApiError(503, "DATA_UNAVAILABLE", message, details)


def error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}
