"""Penanganan galat HTTP server agen."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


_ALLOWED_ERRORS = {
    401: {"unauthorized"},
    404: {"batch_not_found"},
    409: {"plan_version_mismatch", "invalid_state", "gmail_not_connected"},
    422: {"invalid_request"},
    503: {"llm_unavailable", "gmail_unavailable"},
}
_logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Galat aplikasi yang memiliki status dan kode HTTP terkontrol."""

    def __init__(self, status: int, code: str, message: str) -> None:
        if code not in _ALLOWED_ERRORS.get(status, set()):
            raise ValueError("Pasangan status dan kode galat tidak diizinkan.")
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


async def agent_error_handler(request: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Permintaan tidak valid.",
            }
        },
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _logger.error("Galat internal server agen (%s).", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Kesalahan internal.",
            }
        },
    )
