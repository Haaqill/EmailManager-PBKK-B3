"""Pengaturan server agen yang dibaca dari environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    agent_token: str
    agent_port: int = 8765
    agent_registry_path: str = ""
    host: str = field(default="127.0.0.1", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_token, str) or len(self.agent_token) < 32:
            raise ValueError("AGENT_TOKEN wajib berisi minimal 32 karakter.")
        if not 1 <= self.agent_port <= 65535:
            raise ValueError("AGENT_PORT harus berupa port valid.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if environ is None else environ
        token = values.get("AGENT_TOKEN", "")
        try:
            port = int(values.get("AGENT_PORT", "8765"))
        except ValueError:
            raise ValueError("AGENT_PORT harus berupa port valid.") from None
        return cls(
            agent_token=token,
            agent_port=port,
            agent_registry_path=values.get("AGENT_REGISTRY_PATH", ""),
        )
