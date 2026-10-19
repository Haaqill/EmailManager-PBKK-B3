"""Loop ReAct untuk perintah bebas (setelah MVP, A).

STUB. Di MVP, LLM tidak memanggil tool Gmail langsung; workflow di graph.py
yang menjalankan tool. Akan diisi setelah demo MVP lolos:
- tool_calls lengkap beserta tool_call_id (format OpenAI native)
- tanpa sys.path.append; skema dari app.gmail.schemas.openai_tool_schemas
- allowlist tool per tugas, max_steps, batas token, deteksi panggilan berulang
- gate: perintah "rangkum 10 email belum dibaca" berhasil end-to-end
"""
from __future__ import annotations


class ReActLoop:
    """Loop ReAct native di atas LLMClient dan dispatcher."""

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("ReActLoop: setelah MVP (A)")

    def run(self, goal: str) -> str:
        raise NotImplementedError("ReActLoop.run: setelah MVP (A)")
