"""Antarmuka LLMClient (kontrak 1, final).

Implementasi nyata:
- app/llm/campus.py → CampusLLM (M1, A)
- app/llm/mock.py   → MockLLM   (M1, A)
"""
from __future__ import annotations

from typing import Protocol

from app.contracts import LLMResponse, LLMUnavailableError, LLMOutputError

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LLMUnavailableError",
    "LLMOutputError",
]


class LLMClient(Protocol):
    """Protokol yang harus dipenuhi CampusLLM dan MockLLM.

    Kontrak:
    - Satu fungsi sync: call_llm(messages, tools) -> LLMResponse
    - Format internal selalu OpenAI Chat Completions
    - Raise LLMUnavailableError jika server mati setelah retry
    - Raise LLMOutputError jika output tetap rusak setelah 2 koreksi
    """

    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse: ...
    