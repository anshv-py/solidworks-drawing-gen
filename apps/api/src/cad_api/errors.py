"""Domain errors -> RFC 9457 application/problem+json."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    status = 400
    code = "BAD_REQUEST"

    def __init__(self, detail: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        if status:
            self.status = status


class NotFound(ApiError):
    status, code = 404, "NOT_FOUND"


class Conflict(ApiError):
    status, code = 409, "CONFLICT"


class UnsupportedFile(ApiError):
    status, code = 415, "UNSUPPORTED_FILE_TYPE"


class FileTooLarge(ApiError):
    status, code = 413, "FILE_TOO_LARGE"


class NotImplementedYet(ApiError):
    status, code = 501, "NOT_IMPLEMENTED"


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            media_type="application/problem+json",
            content={
                "type": f"urn:cad-drawing-ai:error:{exc.code.lower()}",
                "title": exc.code.replace("_", " ").title(),
                "status": exc.status,
                "detail": exc.detail,
                "code": exc.code,
            },
        )
