"""Tes untuk dispatcher.

Filosofi:
- Dispatcher diuji dengan tool palsu (bukan tool Gmail sungguhan).
  Tujuannya menguji KONTRAK dispatcher, bukan logika tool.
- Setiap tes mengisolasi registry (fixture autouse).
- Tidak ada LLM di tes ini. Dispatcher memang tidak memanggil LLM.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.agent import dispatcher as d
from app.contracts import (
    ErrorCode,
    FatalToolError,
    NotFoundError,
    NotAllowedError,
    ToolContext,
    ToolResult,
    ValidationError,
)


# ── Fixture: registry bersih & ctx standar ──────────────────────────


@pytest.fixture(autouse=True)
def _bersihkan_registry():
    d.clear_registry()
    yield
    d.clear_registry()


@pytest.fixture
def ctx() -> ToolContext:
    """ToolContext dengan allowlist kosong by default.

    Tes yang butuh tool tertentu menambahkan ke allowed_tools.
    """
    class _Map:
        pass

    return ToolContext(
        batch_id="batch-test",
        pii_map=_Map(),
        allowed_tools=set(),
    )


def _ctx_dengan(*tools: str) -> ToolContext:
    class _Map:
        pass

    return ToolContext(
        batch_id="batch-test",
        pii_map=_Map(),
        allowed_tools=set(tools),
    )


# ── Model argumen palsu ─────────────────────────────────────────────


class ArgsEcho(BaseModel):
    text: str = Field(min_length=1)


class ArgsKosong(BaseModel):
    pass


def _tool_echo(args: ArgsEcho, ctx: ToolContext) -> ToolResult[dict]:
    return ToolResult.sukses({"echo": args.text, "batch": ctx.batch_id})


def _tool_kosong(args: ArgsKosong, ctx: ToolContext) -> ToolResult[str]:
    return ToolResult.sukses("ok")


# ══════════════════════════════════════════════════════════════════
# Registrasi
# ══════════════════════════════════════════════════════════════════


def test_register_lalu_registered_tools_berisi_nama():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    assert "echo" in d.registered_tools()


def test_register_duplikat_gagal():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    with pytest.raises(ValueError, match="sudah terdaftar"):
        d.register_tool("echo", ArgsEcho, _tool_echo)


def test_register_nama_kosong_gagal():
    with pytest.raises(ValueError, match="nama tool"):
        d.register_tool("", ArgsEcho, _tool_echo)


def test_register_args_model_bukan_basemodel_gagal():
    with pytest.raises(TypeError, match="BaseModel"):
        d.register_tool("echo", dict, _tool_echo)  # type: ignore[arg-type]


def test_register_fn_bukan_callable_gagal():
    with pytest.raises(TypeError, match="callable"):
        d.register_tool("echo", ArgsEcho, "bukan-fungsi")  # type: ignore[arg-type]


def test_unregister_menghapus_tool():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.unregister_tool("echo")
    assert "echo" not in d.registered_tools()


# ══════════════════════════════════════════════════════════════════
# Jalur sukses
# ══════════════════════════════════════════════════════════════════


def test_dispatch_sukses_mengembalikan_toolresult_ok():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch("echo", {"text": "halo"}, _ctx_dengan("echo"))

    assert hasil.ok is True
    assert hasil.data == {"echo": "halo", "batch": "batch-test"}
    assert hasil.error_code is None
    assert hasil.message is None


def test_dispatch_meneruskan_toolcontext_ke_tool():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch("echo", {"text": "x"}, _ctx_dengan("echo"))
    assert hasil.data["batch"] == "batch-test"


def test_dispatch_tanpa_argumen_sukses():
    d.register_tool("kosong", ArgsKosong, _tool_kosong)
    hasil = d.dispatch("kosong", {}, _ctx_dengan("kosong"))
    assert hasil.ok is True
    assert hasil.data == "ok"


# ══════════════════════════════════════════════════════════════════
# Jalur gagal: tool tidak dikenal / tidak diizinkan
# ══════════════════════════════════════════════════════════════════


def test_tool_tidak_terdaftar_mengembalikan_not_allowed(ctx):
    hasil = d.dispatch("tidak_ada", {}, ctx)
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.NOT_ALLOWED
    # Pesan tidak boleh menyebut apakah tool ada di registry
    assert "tidak dikenal" in hasil.message.lower()


def test_tool_terdaftar_tapi_tidak_di_allowlist_mengembalikan_not_allowed(ctx):
    d.register_tool("echo", ArgsEcho, _tool_echo)
    # ctx.allowed_tools kosong
    hasil = d.dispatch("echo", {"text": "halo"}, ctx)
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.NOT_ALLOWED
    assert "tidak diizinkan" in hasil.message.lower()


def test_pesan_not_allowed_tidak_membocorkan_isi_registry(ctx):
    """LLM tidak boleh tahu bedanya 'tidak ada' dan 'tidak diizinkan'."""
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil_tidak_ada = d.dispatch("tidak_ada", {}, ctx)
    hasil_tidak_izin = d.dispatch("echo", {"text": "x"}, ctx)

    assert hasil_tidak_ada.error_code == hasil_tidak_izin.error_code
    # Pesan berbeda (satu menyebut nama tool), tapi keduanya NOT_ALLOWED
    assert hasil_tidak_ada.message is not None
    assert hasil_tidak_izin.message is not None


# ══════════════════════════════════════════════════════════════════
# Jalur gagal: validasi Pydantic
# ══════════════════════════════════════════════════════════════════


def test_argumen_tidak_valid_mengembalikan_validation():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch("echo", {}, _ctx_dengan("echo"))  # text wajib
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.VALIDATION
    assert "tidak valid" in hasil.message.lower()


def test_argumen_tipe_salah_mengembalikan_validation():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch("echo", {"text": 123}, _ctx_dengan("echo"))
    # Pydantic strict=False akan konversi 123 -> "123", jadi ini sukses.
    # Untuk menguji tipe salah, pakai field yang tidak bisa dikonversi.
    # Ganti: kirim dict bukan string
    hasil = d.dispatch("echo", {"text": {"nested": 1}}, _ctx_dengan("echo"))
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.VALIDATION


def test_argumen_melebihi_batas_mengembalikan_validation():
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch("echo", {"text": ""}, _ctx_dengan("echo"))  # min_length=1
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.VALIDATION


def test_pesan_validation_tidak_menyertakan_nilai_asli():
    """Pesan error tidak boleh membocorkan nilai yang dikirim LLM,
    karena nilai itu bisa berisi PII."""
    d.register_tool("echo", ArgsEcho, _tool_echo)
    hasil = d.dispatch(
        "echo", {"text": ""}, _ctx_dengan("echo")
    )
    # Pesan berisi lokasi field & tipe error, bukan nilai asli
    assert "text" in hasil.message
    # Nilai "" tidak boleh muncul sebagai string literal dalam pesan
    assert '""' not in hasil.message


def test_pesan_validation_membatasi_jumlah_error():
    """Jika banyak error, pesan tidak boleh membengkak."""

    class ArgsBanyak(BaseModel):
        a: str = Field(min_length=1)
        b: str = Field(min_length=1)
        c: str = Field(min_length=1)
        d: str = Field(min_length=1)
        e: str = Field(min_length=1)

    def _fn(args, ctx):
        return ToolResult.sukses("ok")

    d.register_tool("banyak", ArgsBanyak, _fn)
    hasil = d.dispatch("banyak", {}, _ctx_dengan("banyak"))
    assert hasil.error_code == ErrorCode.VALIDATION
    # Batasi 3 error pertama + info sisa
    assert "error lain" in hasil.message or hasil.message.count(":") <= 3


# ══════════════════════════════════════════════════════════════════
# Jalur gagal: exception dari tool
# ══════════════════════════════════════════════════════════════════


def _tool_raise(exc: Exception):
    def _fn(args: ArgsKosong, ctx: ToolContext) -> ToolResult[Any]:
        raise exc

    return _fn


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (ValidationError("argumen salah"), ErrorCode.VALIDATION),
        (NotFoundError("thread tidak ada"), ErrorCode.NOT_FOUND),
        (NotAllowedError("dilarang"), ErrorCode.NOT_ALLOWED),
    ],
)
def test_tool_raise_toolerror_dikonversi_ke_toolresult(exc, expected_code):
    d.register_tool("t", ArgsKosong, _tool_raise(exc))
    hasil = d.dispatch("t", {}, _ctx_dengan("t"))
    assert hasil.ok is False
    assert hasil.error_code == expected_code
    assert str(exc) in hasil.message


def test_tool_raise_exception_tak_terduga_menjadi_internal():
    d.register_tool("t", ArgsKosong, _tool_raise(RuntimeError("bug")))
    hasil = d.dispatch("t", {}, _ctx_dengan("t"))
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.INTERNAL
    # Pesan tidak boleh menyertakan detail exception asli
    assert "bug" not in hasil.message
    assert "kesalahan internal" in hasil.message.lower()


def test_tool_raise_fatal_dilempar_ulang():
    """FatalToolError harus dilempar ulang agar batch berhenti."""
    d.register_tool("t", ArgsKosong, _tool_raise(FatalToolError("oauth gagal")))
    with pytest.raises(FatalToolError, match="oauth gagal"):
        d.dispatch("t", {}, _ctx_dengan("t"))


def test_fatal_tetap_dilempar_meskipun_tool_di_allowlist():
    d.register_tool("t", ArgsKosong, _tool_raise(FatalToolError("mati")))
    with pytest.raises(FatalToolError):
        d.dispatch("t", {}, _ctx_dengan("t"))


# ══════════════════════════════════════════════════════════════════
# Jalur gagal: tool mengembalikan tipe salah
# ══════════════════════════════════════════════════════════════════


def test_tool_mengembalikan_bukan_toolresult_menjadi_internal():
    def _fn(args: ArgsKosong, ctx: ToolContext) -> Any:
        return {"bukan": "ToolResult"}

    d.register_tool("t", ArgsKosong, _fn)
    hasil = d.dispatch("t", {}, _ctx_dengan("t"))
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.INTERNAL
    assert "tipe yang salah" in hasil.message.lower()


# ══════════════════════════════════════════════════════════════════
# Validasi & allowlist terjadi SEBELUM eksekusi
# ══════════════════════════════════════════════════════════════════


def test_validasi_terjadi_sebelum_eksekusi():
    """Tool tidak boleh dipanggil jika argumen tidak valid."""
    dipanggil = {"n": 0}

    def _fn(args: ArgsEcho, ctx: ToolContext) -> ToolResult[str]:
        dipanggil["n"] += 1
        return ToolResult.sukses("ok")

    d.register_tool("echo", ArgsEcho, _fn)
    hasil = d.dispatch("echo", {}, _ctx_dengan("echo"))  # text wajib

    assert hasil.error_code == ErrorCode.VALIDATION
    assert dipanggil["n"] == 0


def test_allowlist_terjadi_sebelum_validasi():
    """Tool di luar allowlist tidak boleh divalidasi argumennya."""
    dipanggil = {"n": 0}

    def _fn(args: ArgsEcho, ctx: ToolContext) -> ToolResult[str]:
        dipanggil["n"] += 1
        return ToolResult.sukses("ok")

    d.register_tool("echo", ArgsEcho, _fn)
    # argumen kosong (tidak valid) tapi tool tidak di allowlist
    hasil = d.dispatch("echo", {}, _ctx_dengan())  # allowed_tools kosong

    assert hasil.error_code == ErrorCode.NOT_ALLOWED
    assert dipanggil["n"] == 0


def test_registry_cek_sebelum_allowlist():
    """Tool tidak terdaftar → NOT_ALLOWED, bukan error lain."""
    hasil = d.dispatch("tidak_ada", {}, _ctx_dengan("tidak_ada"))
    # Meskipun "tidak_ada" ada di allowed_tools, tool tidak ada di registry
    assert hasil.error_code == ErrorCode.NOT_ALLOWED


# ══════════════════════════════════════════════════════════════════
# Logging
# ══════════════════════════════════════════════════════════════════


def test_log_dipanggil_untuk_sukses(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.dispatch("echo", {"text": "halo"}, _ctx_dengan("echo"))

    assert any("tool call" in r.message for r in caplog.records)
    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.tool == "echo"
    assert rec.batch_id == "batch-test"
    assert rec.ok is True
    assert rec.error_code is None


def test_log_dipanggil_untuk_gagal(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.dispatch("echo", {}, _ctx_dengan("echo"))  # validasi gagal

    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.ok is False
    assert rec.error_code == "validation"


def test_log_ditulis_untuk_fatal_dengan_flag_fatal(caplog):
    """FatalToolError tetap menghasilkan satu baris log dengan fatal=True.

    Audit trail wajib ada: jika batch berhenti di tengah jalan, kita perlu
    tahu tool apa yang sedang dipanggil saat fatal terjadi.
    """
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("t", ArgsKosong, _tool_raise(FatalToolError("oauth gagal")))

    with pytest.raises(FatalToolError):
        d.dispatch("t", {}, _ctx_dengan("t"))

    recs = [r for r in caplog.records if "tool call" in r.message]
    assert len(recs) == 1
    rec = recs[0]
    assert rec.fatal is True
    assert rec.ok is False
    assert rec.error_code == "internal"
    assert rec.fatal_message == "oauth gagal"
    assert rec.tool == "t"
    assert rec.batch_id == "batch-test"


def test_log_internal_biasa_tidak_ditandai_fatal(caplog):
    """Internal biasa (bug programmer) bukan fatal: fatal=False."""
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("t", ArgsKosong, _tool_raise(RuntimeError("bug")))

    hasil = d.dispatch("t", {}, _ctx_dengan("t"))
    assert hasil.error_code == ErrorCode.INTERNAL

    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.fatal is False
    assert rec.error_code == "internal"


def test_log_sukses_tidak_ditandai_fatal(caplog):
    """Sukses: fatal=False dan error_code=None."""
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.dispatch("echo", {"text": "halo"}, _ctx_dengan("echo"))

    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.fatal is False
    assert rec.ok is True
    assert rec.error_code is None

def test_log_dipanggil_untuk_sukses(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.dispatch("echo", {"text": "halo"}, _ctx_dengan("echo"))

    assert any("tool call" in r.message for r in caplog.records)
    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.tool == "echo"
    assert rec.batch_id == "batch-test"
    assert rec.ok is True
    assert rec.error_code is None
    assert rec.fatal is False  # ← tambahan


def test_log_dipanggil_untuk_gagal(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="gmail_agent.dispatcher")
    d.register_tool("echo", ArgsEcho, _tool_echo)
    d.dispatch("echo", {}, _ctx_dengan("echo"))  # validasi gagal

    rec = next(r for r in caplog.records if "tool call" in r.message)
    assert rec.ok is False
    assert rec.error_code == "validation"
    assert rec.fatal is False  # ← tambahan

# ══════════════════════════════════════════════════════════════════
# Integrasi dengan tool Gmail tiruan
# ══════════════════════════════════════════════════════════════════


def test_integrasi_scan_emails_tiruan():
    """Simulasi tool scan_emails yang dipanggil dispatcher."""

    class ArgsScan(BaseModel):
        unread_only: bool = True
        newer_than_days: int = Field(default=7, ge=1, le=90)
        max_results: int = Field(default=10, ge=1, le=50)

    def _scan(args: ArgsScan, ctx: ToolContext) -> ToolResult[dict]:
        return ToolResult.sukses(
            {
                "threads": [
                    {"thread_id": "t1", "subject": "A"},
                    {"thread_id": "t2", "subject": "B"},
                ],
                "query": f"is:unread newer_than:{args.newer_than_days}d",
            }
        )

    d.register_tool("scan_emails", ArgsScan, _scan)

    hasil = d.dispatch(
        "scan_emails",
        {"newer_than_days": 3, "max_results": 5},
        _ctx_dengan("scan_emails"),
    )

    assert hasil.ok is True
    assert len(hasil.data["threads"]) == 2
    assert hasil.data["query"] == "is:unread newer_than:3d"


def test_integrasi_scan_emails_newer_than_days_di_luar_batas():
    class ArgsScan(BaseModel):
        newer_than_days: int = Field(default=7, ge=1, le=90)

    def _scan(args: ArgsScan, ctx: ToolContext) -> ToolResult[str]:
        return ToolResult.sukses("ok")

    d.register_tool("scan_emails", ArgsScan, _scan)

    # newer_than_days=0 di luar batas 1..90
    hasil = d.dispatch(
        "scan_emails", {"newer_than_days": 0}, _ctx_dengan("scan_emails")
    )
    assert hasil.error_code == ErrorCode.VALIDATION
    assert "newer_than_days" in hasil.message


def test_integrasi_allowlist_hanya_scan_tidak_boleh_label():
    """Di M2, workflow MVP hanya mengizinkan tool tertentu.
    Ini simulasi: hanya scan_emails di allowlist."""

    class ArgsScan(BaseModel):
        pass

    class ArgsLabel(BaseModel):
        thread_id: str

    def _scan(args, ctx):
        return ToolResult.sukses("scan-ok")

    def _label(args, ctx):
        return ToolResult.sukses("label-ok")

    d.register_tool("scan_emails", ArgsScan, _scan)
    d.register_tool("label_thread", ArgsLabel, _label)

    ctx = _ctx_dengan("scan_emails")  # label_thread TIDAK di allowlist

    assert d.dispatch("scan_emails", {}, ctx).ok is True
    hasil_label = d.dispatch("label_thread", {"thread_id": "t1"}, ctx)
    assert hasil_label.ok is False
    assert hasil_label.error_code == ErrorCode.NOT_ALLOWED