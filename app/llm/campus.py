"""CampusLLM — endpoint OpenAI dengan adapter ollama (M1, A).

STUB. Implementasi diisi di M1 setelah smoke test API kampus selesai.
"""
from __future__ import annotations

from app.contracts import LLMResponse


class CampusLLM:
    """Implementasi LLMClient untuk endpoint kampus.

    Akan diisi di M1:
    - endpoint OpenAI Chat Completions
    - fallback json otomatis
    - koreksi output rusak maks 2x
    - retry server mati maks 3x dengan tenacity + jitter
    - usage dijumlahkan lintas percobaan
    - adapter ollama jika /v1/chat/completions tidak tersedia
    """

    def __init__(self, config=None) -> None:
        raise NotImplementedError("CampusLLM: diisi di M1 (A)")

    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        raise NotImplementedError("CampusLLM.call_llm: diisi di M1 (A)")