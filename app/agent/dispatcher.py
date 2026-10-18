"""Dispatcher — pintu masuk tunggal ke semua tool (M1, A).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations

from typing import Any

from app.contracts import ToolContext, ToolResult


def dispatch(tool_name: str, arguments: dict, ctx: ToolContext) -> ToolResult[Any]:
    """STUB: validasi Pydantic, cek allowlist, eksekusi tool.

    A akan mengganti dengan:
    - validasi arguments Pydantic → VALIDATION jika gagal
    - cek tool_name ∈ ctx.allowed_tools → NOT_ALLOWED jika tidak
    - eksekusi tool dengan ToolContext
    - exception → ToolResult dengan error_code sesuai
    - satu baris log per panggilan (via logger C)
    """
    raise NotImplementedError("dispatcher.dispatch: diisi di M1 (A)")