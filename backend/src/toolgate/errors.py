from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from toolgate.logging import get_logger

log = get_logger(__name__)


class ToolgateError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(ToolgateError):
    status_code = 404
    code = "not_found"


class ConflictError(ToolgateError):
    status_code = 409
    code = "conflict"


class UnprocessableError(ToolgateError):
    status_code = 422
    code = "unprocessable"


class UnauthorizedError(ToolgateError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(ToolgateError):
    status_code = 403
    code = "forbidden"


class UpstreamUnavailableError(ToolgateError):
    status_code = 503
    code = "upstream_unavailable"


def _problem(status: int, code: str, detail: str, extra: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": f"urn:toolgate:error:{code}", "title": code, "status": status, "detail": detail}
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ToolgateError)
    async def _toolgate_error(_: Request, exc: ToolgateError) -> JSONResponse:
        return _problem(exc.status_code, exc.code, exc.detail, exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
            for err in exc.errors()
        ]
        return _problem(422, "validation_failed", "Request validation failed", {"errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path, error=type(exc).__name__)
        return _problem(500, "internal_error", "An unexpected error occurred")
