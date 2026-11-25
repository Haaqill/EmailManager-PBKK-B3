"""Route HTTP untuk batch dan autentikasi Gmail."""
from __future__ import annotations

import json
from typing import TypeVar

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from app.gmail.auth import (
    OAuthConfigurationError,
    ReauthRequired,
    auth_status,
    begin_login,
)
from app.gmail.factory import GmailConfigError, gmail_backend
from app.server.errors import AgentError
from app.server.manager import BatchManager
from app.server.schemas import (
    AuthStatusResponse,
    BeginLoginResponse,
    ExecuteBatchRequest,
    StartBatchRequest,
)

_MOCK_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth?mock=1"
RequestT = TypeVar("RequestT", bound=BaseModel)


async def _parse_body(request: Request, model: type[RequestT]) -> RequestT:
    try:
        body = await request.json()
        return model.model_validate(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise AgentError(
            422, "invalid_request", "Permintaan tidak valid."
        ) from None


def create_router(manager: BatchManager) -> APIRouter:
    from app.server.app import get_current_user

    router = APIRouter()

    @router.post("/v1/batches", status_code=202)
    async def start_batch(request: Request):
        user_id = await get_current_user(request)
        body = await _parse_body(request, StartBatchRequest)
        return manager.start_batch(user_id, body.filters.max_results)

    @router.get("/v1/batches/{batch_id}")
    async def get_batch(batch_id: str, request: Request):
        user_id = await get_current_user(request)
        return manager.get_batch(batch_id, user_id)

    @router.post("/v1/batches/{batch_id}/execute", status_code=202)
    async def execute_batch(batch_id: str, request: Request):
        user_id = await get_current_user(request)
        manager.require_owned(batch_id, user_id)
        body = await _parse_body(request, ExecuteBatchRequest)
        return manager.execute(batch_id, user_id, body)

    @router.post("/v1/batches/{batch_id}/cancel", status_code=202)
    async def cancel_batch(batch_id: str, request: Request):
        user_id = await get_current_user(request)
        return manager.cancel(batch_id, user_id)

    @router.get("/v1/auth/status", response_model=AuthStatusResponse)
    async def get_auth_status(request: Request):
        user_id = await get_current_user(request)
        try:
            backend = gmail_backend()
        except GmailConfigError:
            raise AgentError(
                503, "gmail_unavailable", "Gmail tidak tersedia."
            ) from None
        if backend == "mock":
            return {"status": "connected"}
        try:
            return {"status": auth_status(user_id)}
        except ReauthRequired:
            raise AgentError(
                503, "gmail_unavailable", "Gmail tidak tersedia."
            ) from None

    @router.post("/v1/auth/login", response_model=BeginLoginResponse)
    async def start_login(request: Request):
        user_id = await get_current_user(request)
        try:
            backend = gmail_backend()
        except GmailConfigError:
            raise AgentError(
                503, "gmail_unavailable", "Gmail tidak tersedia."
            ) from None
        if backend == "mock":
            return {"auth_url": _MOCK_AUTH_URL}
        try:
            return {"auth_url": begin_login(user_id)}
        except (OAuthConfigurationError, FileNotFoundError):
            raise AgentError(
                503, "gmail_unavailable", "Gmail tidak tersedia."
            ) from None

    return router
