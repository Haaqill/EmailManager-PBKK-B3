"""Tes untuk MockLLM dan helper pembuat LLMResponse.

Filosofi tes:
- Fokus ke perilaku yang AKAN dipakai workflow M2 dan CampusLLM M1:
  antrean, rekaman panggilan, simulasi error, bentuk tool_calls.
- Tidak menguji koreksi/retry — itu tanggung jawab CampusLLM, bukan MockLLM.
- Tidak menguji usage secara numerik ketat (bisa berubah), cukup
  memastikan field terisi dan konsisten.
"""
from __future__ import annotations

import pytest

from app.contracts import (
    LLMOutputError,
    LLMResponse,
    LLMUnavailableError,
    ToolCall,
    Usage,
)
from app.llm.mock import (
    MockLLM,
    make_multi_tool_response,
    make_text_response,
    make_tool_response,
)


# ── Fixture umum ────────────────────────────────────────────────────


def _teks(content: str = "halo") -> LLMResponse:
    return make_text_response(content)


def _tool(nama: str = "submit_classification", args: dict | None = None):
    return make_tool_response(nama, args or {"thread_id": "t1"})


# ── Perilaku dasar: antrean & rekaman ───────────────────────────────


def test_mengembalikan_respons_sesuai_urutan_antrean():
    r1 = _teks("satu")
    r2 = _teks("dua")
    r3 = _teks("tiga")
    llm = MockLLM([r1, r2, r3])

    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "satu"
    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "dua"
    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "tiga"
    assert llm.remaining == 0


def test_mencatat_panggilan_ke_calls():
    llm = MockLLM([_teks("ok")])
    msgs = [{"role": "system", "content": "kamu asisten"}]
    tools = [{"type": "function", "function": {"name": "submit_classification"}}]

    llm.call_llm(msgs, tools)

    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"] == msgs
    assert llm.calls[0]["tools"] == tools


def test_calls_merekan_copy_bukan_referensi():
    """Tes tidak boleh bisa memutasi rekaman setelah panggilan."""
    llm = MockLLM([_teks("ok")])
    msgs = [{"role": "user", "content": "asli"}]

    llm.call_llm(msgs)
    msgs[0]["content"] = "diubah"

    assert llm.calls[0]["messages"][0]["content"] == "asli"


def test_tools_none_direkam_sebagai_none():
    llm = MockLLM([_teks("ok")])
    llm.call_llm([{"role": "user", "content": "x"}])
    assert llm.calls[0]["tools"] is None


# ── Perilaku gagal: antrean habis ────────────────────────────────────


def test_antrean_habis_raise_assertion_error():
    llm = MockLLM([])
    with pytest.raises(AssertionError, match="kehabisan respons"):
        llm.call_llm([{"role": "user", "content": "x"}])


def test_antrean_habis_setelah_beberapa_panggilan():
    llm = MockLLM([_teks("satu")])
    llm.call_llm([{"role": "user", "content": "x"}])
    with pytest.raises(AssertionError, match="kehabisan respons"):
        llm.call_llm([{"role": "user", "content": "x"}])


def test_pesan_assertion_menyebut_nomor_panggilan():
    llm = MockLLM([_teks("satu")])
    llm.call_llm([{"role": "user", "content": "x"}])
    with pytest.raises(AssertionError, match="Panggilan ke-2"):
        llm.call_llm([{"role": "user", "content": "x"}])


# ── Perilaku gagal: simulasi error ───────────────────────────────────


def test_bisa_mensimulasikan_llm_unavailable_error():
    llm = MockLLM([LLMUnavailableError("server mati")])
    with pytest.raises(LLMUnavailableError, match="server mati"):
        llm.call_llm([{"role": "user", "content": "x"}])
    assert llm.remaining == 0


def test_bisa_mensimulasikan_llm_output_error():
    llm = MockLLM([LLMOutputError("json rusak")])
    with pytest.raises(LLMOutputError, match="json rusak"):
        llm.call_llm([{"role": "user", "content": "x"}])


def test_error_setelah_respons_sukses():
    llm = MockLLM([_teks("ok"), LLMUnavailableError("mati")])
    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "ok"
    with pytest.raises(LLMUnavailableError):
        llm.call_llm([{"role": "user", "content": "x"}])


def test_error_tetap_mencatat_panggilan():
    llm = MockLLM([LLMUnavailableError("mati")])
    with pytest.raises(LLMUnavailableError):
        llm.call_llm([{"role": "user", "content": "x"}])
    assert len(llm.calls) == 1


# ── Utilitas: push, reset, remaining ────────────────────────────────


def test_push_menambah_ke_ujung_antrean():
    llm = MockLLM([_teks("satu")])
    llm.push(_teks("dua"), _teks("tiga"))
    assert llm.remaining == 3
    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "satu"
    assert llm.call_llm([{"role": "user", "content": "x"}]).content == "dua"


def test_reset_mengosongkan_antrean_dan_calls():
    llm = MockLLM([_teks("satu")])
    llm.call_llm([{"role": "user", "content": "x"}])
    llm.reset()
    assert llm.remaining == 0
    assert llm.calls == []


def test_remaining_awal_sama_dengan_jumlah_respons():
    llm = MockLLM([_teks(), _teks(), _teks()])
    assert llm.remaining == 3


# ── Bentuk tool_call ────────────────────────────────────────────────


def test_tool_response_berisi_satu_tool_call():
    r = make_tool_response(
        "submit_classification",
        {"thread_id": "t1", "category": "Tugas"},
    )
    assert r.content is None
    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.name == "submit_classification"
    assert tc.arguments == {"thread_id": "t1", "category": "Tugas"}
    assert tc.id == "call_submit_classification_1"


def test_tool_response_id_bisa_ditentukan():
    r = make_tool_response(
        "submit_draft", {"body": "ok"}, tool_call_id="my-id-123"
    )
    assert r.tool_calls[0].id == "my-id-123"


def test_tool_response_bisa_berisi_content_juga():
    r = make_tool_response(
        "submit_classification",
        {"thread_id": "t1"},
        content="Saya klasifikasikan sebagai Tugas.",
    )
    assert r.content == "Saya klasifikasikan sebagai Tugas."
    assert len(r.tool_calls) == 1


def test_multi_tool_response_berisi_beberapa_tool_call():
    r = make_multi_tool_response(
        [
            ("submit_classification", {"thread_id": "t1"}),
            ("submit_draft", {"thread_id": "t1", "body": "ok"}),
        ]
    )
    assert len(r.tool_calls) == 2
    assert r.tool_calls[0].name == "submit_classification"
    assert r.tool_calls[1].name == "submit_draft"
    assert r.tool_calls[0].id != r.tool_calls[1].id


def test_multi_tool_response_ids_bisa_ditentukan():
    r = make_multi_tool_response(
        [("a", {}), ("b", {})],
        ids=["id-a", "id-b"],
    )
    assert [tc.id for tc in r.tool_calls] == ["id-a", "id-b"]


def test_multi_tool_response_ids_panjang_tidak_cocok_gagal():
    with pytest.raises(ValueError, match="panjang sama"):
        make_multi_tool_response([("a", {})], ids=["id-a", "id-b"])


# ── Bentuk response teks ────────────────────────────────────────────


def test_text_response_tidak_punya_tool_calls():
    r = make_text_response("halo dunia")
    assert r.content == "halo dunia"
    assert r.tool_calls == []


# ── Usage ───────────────────────────────────────────────────────────


def test_usage_terisi_setelah_panggilan():
    llm = MockLLM([_teks("empat karakter")])
    r = llm.call_llm([{"role": "user", "content": "x" * 100}])

    assert isinstance(r.usage, Usage)
    assert r.usage.model == "mock-llm"
    assert r.usage.api_style == "openai"
    assert r.usage.tool_mode == "json"
    assert r.usage.retries == 0
    assert r.usage.latency_ms == 0
    assert r.usage.prompt_tokens is not None
    assert r.usage.completion_tokens is not None
    assert r.usage.total_tokens == (
        r.usage.prompt_tokens + r.usage.completion_tokens
    )


def test_usage_deterministik_untuk_input_sama():
    """Dua MockLLM dengan respons sama harus menghasilkan usage identik."""
    llm1 = MockLLM([make_text_response("abc", prompt_chars=100)])
    llm2 = MockLLM([make_text_response("abc", prompt_chars=100)])

    u1 = llm1.call_llm([{"role": "user", "content": "x"}]).usage
    u2 = llm2.call_llm([{"role": "user", "content": "x"}]).usage

    assert u1 == u2


def test_usage_completion_nol_untuk_tool_call_tanpa_content():
    r = make_tool_response("submit_draft", {"body": "hi"})
    assert r.usage.completion_tokens is not None
    # tool call tanpa content: completion_tokens dihitung dari ukuran args,
    # jadi > 0, tapi total tetap konsisten
    assert r.usage.total_tokens == (
        (r.usage.prompt_tokens or 0) + (r.usage.completion_tokens or 0)
    )


# ── Integrasi dengan alur workflow yang akan datang ─────────────────


def test_skenario_classify_lalu_draft():
    """Simulasi dua panggilan berturut-turut seperti di graph M2."""
    llm = MockLLM(
        [
            make_tool_response(
                "submit_classification",
                {
                    "thread_id": "t1",
                    "summary": "Tugas 3 diperpanjang",
                    "category": "Tugas",
                    "priority": "Mendesak",
                    "action": "keep",
                    "needs_reply": True,
                    "reason": "Perlu konfirmasi",
                },
            ),
            make_tool_response(
                "submit_draft",
                {"thread_id": "t1", "body": "Terima kasih, saya akan kumpulkan."},
            ),
        ]
    )

    r1 = llm.call_llm([{"role": "user", "content": "email 1"}])
    assert r1.tool_calls[0].name == "submit_classification"

    r2 = llm.call_llm([{"role": "user", "content": "email 1 + konteks"}])
    assert r2.tool_calls[0].name == "submit_draft"

    assert len(llm.calls) == 2
    assert llm.remaining == 0


def test_skenario_ditolak_lalu_berhenti():
    """Workflow yang rejected tidak boleh memanggil LLM lagi untuk draft."""
    llm = MockLLM(
        [
            make_tool_response(
                "submit_classification",
                {"thread_id": "t1", "needs_reply": False},
            ),
        ]
    )

    llm.call_llm([{"role": "user", "content": "email"}])

    with pytest.raises(AssertionError, match="kehabisan respons"):
        llm.call_llm([{"role": "user", "content": "draft"}])