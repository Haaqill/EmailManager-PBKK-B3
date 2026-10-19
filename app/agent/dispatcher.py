"""Dispatcher — pintu masuk tunggal ke semua tool.

Aturan (dari tab Kontrak dan panduan):
- Validasi argumen Pydantic SEBELUM eksekusi.
- Cek allowlist SEBELUM eksekusi.
- Exception → ToolResult, KECUALI FatalToolError yang dilempar ulang.
- Satu baris log per panggilan, via logger dari C.
- Dispatcher TIDAK memanggil LLM. LLM hanya mengusulkan tool_call;
  workflow yang memanggil dispatcher.

Kontrak error:
- Pydantic ValidationError → ToolResult(VALIDATION)
- ToolError subclass         → ToolResult(code subclass)
- FatalToolError             → dilempar ulang (batch berhenti)
- Exception lain             → ToolResult(INTERNAL), dicatat sebagai bug
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.contracts import (
    ErrorCode,
    FatalToolError,
    NotFoundError,
    NotAllowedError,
    ToolContext,
    ToolError,
    ToolResult,
    ValidationError,
)
from app.privacy.redact import redact

logger = logging.getLogger("gmail_agent.dispatcher")


# Tipe fungsi tool: (args: BaseModel, ctx: ToolContext) -> ToolResult
ToolFn = Callable[[BaseModel, ToolContext], ToolResult[Any]]

# Registry: nama tool → (model argumen, fungsi tool)
_TOOL_REGISTRY: dict[str, tuple[type[BaseModel], ToolFn]] = {}


# ══════════════════════════════════════════════════════════════════
# Registrasi tool
# ══════════════════════════════════════════════════════════════════


def register_tool(
    name: str, args_model: type[BaseModel], fn: ToolFn
) -> None:
    """Daftarkan tool ke dispatcher.

    Dipanggil sekali di modul startup (mis. app/gmail/tools.py saat import).
    Jika nama sudah terdaftar, raise ValueError — mencegah duplikat
    yang membingungkan.
    """
    if not name or not isinstance(name, str):
        raise ValueError("nama tool harus string non-kosong")
    if name in _TOOL_REGISTRY:
        raise ValueError(f"tool {name!r} sudah terdaftar")
    if not issubclass(args_model, BaseModel):
        raise TypeError(f"args_model untuk {name!r} harus BaseModel")
    if not callable(fn):
        raise TypeError(f"fn untuk {name!r} harus callable")

    _TOOL_REGISTRY[name] = (args_model, fn)
    logger.debug("tool terdaftar", extra={"tool": name})


def unregister_tool(name: str) -> None:
    """Hapus tool dari registry. Hanya untuk tes."""
    _TOOL_REGISTRY.pop(name, None)


def clear_registry() -> None:
    """Kosongkan registry. Hanya untuk tes."""
    _TOOL_REGISTRY.clear()


def registered_tools() -> set[str]:
    """Nama semua tool yang terdaftar. Berguna untuk debugging dan tes."""
    return set(_TOOL_REGISTRY.keys())


# ══════════════════════════════════════════════════════════════════
# Dispatch
# ══════════════════════════════════════════════════════════════════


def dispatch(
    tool_name: str, arguments: dict, ctx: ToolContext
) -> ToolResult[Any]:
    """Validasi, cek allowlist, eksekusi tool. Kembalikan ToolResult.

    Raise FatalToolError jika tool raise FatalToolError.
    Tidak pernah raise untuk error lain.
    """
    # 1. Cek tool ada di registry
    if tool_name not in _TOOL_REGISTRY:
        _log(tool_name, arguments, ctx, ok=False, error_code=ErrorCode.NOT_ALLOWED)
        return ToolResult.gagal(
            ErrorCode.NOT_ALLOWED,
            f"Tool {tool_name!r} tidak dikenal.",
        )

    # 2. Cek allowlist
    if tool_name not in ctx.allowed_tools:
        _log(tool_name, arguments, ctx, ok=False, error_code=ErrorCode.NOT_ALLOWED)
        return ToolResult.gagal(
            ErrorCode.NOT_ALLOWED,
            f"Tool {tool_name!r} tidak diizinkan untuk tugas ini.",
        )

    # 3. Validasi argumen dengan Pydantic
    args_model, fn = _TOOL_REGISTRY[tool_name]
    try:
        args = args_model.model_validate(arguments)
    except PydanticValidationError as exc:
        # Pesan aman untuk LLM: ringkas, tanpa stack trace, tanpa nilai asli
        pesan = _format_validation_error(exc)
        _log(tool_name, arguments, ctx, ok=False, error_code=ErrorCode.VALIDATION)
        return ToolResult.gagal(ErrorCode.VALIDATION, pesan)

    # 4. Eksekusi tool
    try:
        hasil = fn(args, ctx)
    except FatalToolError as exc:
        # Batch harus berhenti. Catat sebagai fatal, lalu lempar ulang.
        # Log ditulis agar audit trail menunjukkan tool apa yang
        # sedang dipanggil saat fatal terjadi.
        _log(
            tool_name,
            arguments,
            ctx,
            ok=False,
            error_code=ErrorCode.INTERNAL,
            fatal=True,
            fatal_message=str(exc),
        )
        raise
    except ToolError as exc:
        # ValidationError, NotFoundError, NotAllowedError dari tool
        _log(tool_name, arguments, ctx, ok=False, error_code=exc.code)
        return ToolResult.gagal(exc.code, str(exc))
    except Exception as exc:
        # Bug programmer: catat, jangan koreksi LLM
        logger.error(
            "tool raise exception tak terduga: %s",
            redact(str(exc), ctx.pii_map),
            extra={
                "tool": tool_name,
                "batch_id": ctx.batch_id,
                "exception_type": type(exc).__name__,
            },
        )
        _log(tool_name, arguments, ctx, ok=False, error_code=ErrorCode.INTERNAL)
        return ToolResult.gagal(
            ErrorCode.INTERNAL,
            f"Tool {tool_name!r} gagal karena kesalahan internal.",
        )

    # 5. Verifikasi bentuk hasil
    if not isinstance(hasil, ToolResult):
        logger.error(
            "tool mengembalikan bukan ToolResult",
            extra={"tool": tool_name, "type": type(hasil).__name__},
        )
        _log(tool_name, arguments, ctx, ok=False, error_code=ErrorCode.INTERNAL)
        return ToolResult.gagal(
            ErrorCode.INTERNAL,
            f"Tool {tool_name!r} mengembalikan tipe yang salah.",
        )

    _log(
        tool_name,
        arguments,
        ctx,
        ok=hasil.ok,
        error_code=hasil.error_code,
    )
    return hasil


# ══════════════════════════════════════════════════════════════════
# Helper internal
# ══════════════════════════════════════════════════════════════════


def _format_validation_error(exc: PydanticValidationError) -> str:
    """Ringkas error Pydantic jadi pesan yang aman & berguna untuk LLM.

    Menampilkan lokasi field dan tipe error, TANPA nilai asli
    (untuk menghindari kebocoran PII ke LLM lewat pesan error).
    """
    bagian = []
    for err in exc.errors()[:3]:  # batasi 3 error pertama
        loc = ".".join(str(p) for p in err["loc"])
        bagian.append(f"{loc}: {err['msg']}")
    pesan = "; ".join(bagian)
    if len(exc.errors()) > 3:
        pesan += f"; ... ({len(exc.errors()) - 3} error lain)"
    return f"Argumen tidak valid: {pesan}"


def _log(
    tool_name: str,
    arguments: dict,
    ctx: ToolContext,
    *,
    ok: bool,
    error_code: ErrorCode | None,
    fatal: bool = False,
    fatal_message: str | None = None,
) -> None:
    """Satu baris log per panggilan. Teredaksi oleh logger C (stub dulu).

    Field `fatal=True` menandai bahwa batch dihentikan karena error ini.
    Logger C akan memakai field ini untuk membedakan fatal dari internal
    biasa saat menulis JSONL.
    """
    extra = {
        "batch_id": ctx.batch_id,
        "tool": tool_name,
        "arguments": _redact_log_value(arguments, ctx),
        "ok": ok,
        "error_code": error_code.value if error_code else None,
        "fatal": fatal,
    }
    if fatal_message is not None:
        extra["fatal_message"] = redact(fatal_message, ctx.pii_map)

    logger.info("tool call", extra=extra)


def _redact_log_value(value: Any, ctx: ToolContext) -> Any:
    if isinstance(value, str):
        return redact(value, ctx.pii_map)
    if isinstance(value, dict):
        return {
            _redact_log_value(key, ctx): _redact_log_value(item, ctx)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_log_value(item, ctx) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item, ctx) for item in value)
    return value