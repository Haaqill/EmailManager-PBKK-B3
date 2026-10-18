"""MockLLM — LLM palsu untuk tes (M1, A).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations

from app.contracts import LLMResponse


class MockLLM:
    """LLM palsu yang mengembalikan urutan LLMResponse yang ditentukan tes.

    Akan diisi di M1:
    - queue LLMResponse yang di-pop per panggilan
    - mendukung tool_calls
    - mendukung output rusak untuk menguji koreksi
    - usage palsu yang deterministik
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        raise NotImplementedError("MockLLM: diisi di M1 (A)")

    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        raise NotImplementedError("MockLLM.call_llm: diisi di M1 (A)")