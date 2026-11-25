"""Pabrik aplikasi FastAPI untuk server agen."""
from __future__ import annotations

import re
import secrets
from contextlib import asynccontextmanager
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.gmail.tools import register_all_tools
from app.server.errors import (
    AgentError,
    agent_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.server.settings import Settings

_USER_ID_RE = re.compile(r"^[0-9]{1,18}$")


async def get_current_user(request: Request) -> str:
    """Validasi token lebih dahulu, lalu ID pengguna dari header."""
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.startswith("Bearer "):
        raise AgentError(401, "unauthorized", "Autentikasi diperlukan.")

    supplied_token = authorization[len("Bearer ") :].encode("utf-8")
    expected_token = settings.agent_token.encode("utf-8")
    if not secrets.compare_digest(supplied_token, expected_token):
        raise AgentError(401, "unauthorized", "Autentikasi diperlukan.")

    user_id = request.headers.get("x-user-id")
    if user_id is None or _USER_ID_RE.fullmatch(user_id) is None:
        raise AgentError(422, "invalid_request", "Permintaan tidak valid.")
    return user_id


def create_app(
    settings: Settings,
    registry: Any,
    llm_factory: Any,
    gmail_factory: Any,
    executor: Executor | None = None,
) -> FastAPI:
    """Buat aplikasi dengan seluruh dependensi eksternal diinjeksi."""
    app_executor = executor if executor is not None else ThreadPoolExecutor()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            register_all_tools()
            registry.reconcile_on_start()
            yield
        finally:
            app_executor.shutdown(wait=True)

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        exception_handlers={
            AgentError: agent_error_handler,
            RequestValidationError: validation_error_handler,
            Exception: unexpected_error_handler,
        },
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.llm_factory = llm_factory
    app.state.gmail_factory = gmail_factory
    app.state.executor = app_executor
    return app
