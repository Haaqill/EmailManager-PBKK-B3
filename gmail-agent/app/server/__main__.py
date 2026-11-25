"""Jalankan server agen pada loopback."""
from __future__ import annotations

import uvicorn

from app.gmail.factory import make_gmail_client
from app.llm.client import make_llm
from app.server.app import create_app
from app.server.registry import BatchRegistry
from app.server.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    registry = BatchRegistry(settings.agent_registry_path or None)
    app = create_app(
        settings=settings,
        registry=registry,
        llm_factory=make_llm,
        gmail_factory=make_gmail_client,
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.agent_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
