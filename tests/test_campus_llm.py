"""Tes CampusLLM dengan transport palsu (tanpa jaringan)."""
from __future__ import annotations

import json

import pytest
from tenacity import wait_none

from app.config import Config, ConfigError
from app.contracts import LLMOutputError, LLMUnavailableError
from app.llm.campus import CampusLLM
from app.llm.transport import LLMHTTPError

CFG = Config(llm_backend="campus", llm_api_style="openai", llm_tool_mode="native",
             llm_base_url="https://llm.kampus.ac.id/v1", llm_api_key="sk-uji-123456",
             llm_model="qwen3:14b", eval_dataset_path="eval/dataset.json")
TOOLS = [{"type": "function", "function": {"name": "submit_draft", "parameters": {}}}]


def resp(tool_calls=None, content=None, usage=(10, 5)):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"model": "qwen3:14b-served", "choices": [{"message": msg}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                      "total_tokens": usage[0] + usage[1]}}


def call(name="submit_draft", arguments='{"thread_id": "t1", "body": "Halo"}', id_="c1"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments}}


class FakeSend:
    def __init__(self, *items):
        self.items = list(items)
        self.messages = []

    def __call__(self, cfg, messages, tools=None, **_):
        self.messages.append(list(messages))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, 0.0


def make(*items):
    send = FakeSend(*items)
    return CampusLLM(CFG, send=send, wait=wait_none()), send


def test_arguments_string_diparse_dan_usage():
    llm, _ = make(resp([call()]))
    r = llm.call_llm([{"role": "user", "content": "x"}], TOOLS)
    assert r.tool_calls[0].arguments == {"thread_id": "t1", "body": "Halo"}
    assert r.usage.model == "qwen3:14b-served"
    assert (r.usage.prompt_tokens, r.usage.total_tokens, r.usage.retries) == (10, 15, 0)
    assert (r.usage.api_style, r.usage.tool_mode) == ("openai", "native")


def test_id_yang_hilang_dibuat_dan_arguments_objek_diterima():
    llm, _ = make(resp([{"function": {"name": "submit_draft", "arguments": {"body": "x"}}}]))
    r = llm.call_llm([], TOOLS)
    assert r.tool_calls[0].id == "call_1"
    assert r.tool_calls[0].arguments == {"body": "x"}


def test_teks_biasa_tanpa_tools():
    llm, _ = make(resp(content="halo"))
    r = llm.call_llm([{"role": "user", "content": "hai"}])
    assert (r.content, r.tool_calls) == ("halo", [])


def test_output_rusak_dikoreksi_sekali_lalu_berhasil():
    llm, send = make(resp([call(arguments="{rusak")]), resp([call()]))
    r = llm.call_llm([{"role": "user", "content": "x"}], TOOLS)
    assert r.tool_calls[0].name == "submit_draft"
    assert r.usage.retries == 1
    assert r.usage.total_tokens == 30            # dijumlahkan lintas percobaan
    assert "tidak valid" in send.messages[1][-1]["content"]


def test_output_rusak_setelah_dua_koreksi_menjadi_error():
    llm, _ = make(resp(content="tanpa tool"), resp(content="lagi"), resp(content="tetap"))
    with pytest.raises(LLMOutputError):
        llm.call_llm([], TOOLS)


def test_server_mati_diretry_lalu_berhasil():
    llm, _ = make(LLMHTTPError(503, "down"), LLMHTTPError(None, "timeout"), resp([call()]))
    r = llm.call_llm([], TOOLS)
    assert r.usage.retries == 2


def test_retry_habis_menjadi_unavailable():
    llm, send = make(*[LLMHTTPError(503, "down")] * 4)
    with pytest.raises(LLMUnavailableError):
        llm.call_llm([], TOOLS)
    assert send.items == []                       # 1 + 3 retry


def test_401_tidak_diretry():
    llm, send = make(LLMHTTPError(401, "bad key"), resp([call()]))
    with pytest.raises(LLMUnavailableError):
        llm.call_llm([], TOOLS)
    assert len(send.items) == 1


def test_usage_none_jika_backend_tidak_melapor():
    data = resp([call()])
    del data["usage"]
    llm, _ = make(data)
    assert llm.call_llm([], TOOLS).usage.total_tokens is None


@pytest.mark.parametrize("field,value", [("llm_tool_mode", "json"), ("llm_api_style", "ollama")])
def test_mode_selain_native_openai_ditolak(field, value):
    cfg = Config(**{**CFG.__dict__, field: value})
    with pytest.raises(ConfigError):
        CampusLLM(cfg, send=FakeSend())


def test_api_key_tidak_bocor_di_pesan_error():
    llm, _ = make(*[LLMHTTPError(500, "x")] * 4)
    with pytest.raises(LLMUnavailableError) as info:
        llm.call_llm([], TOOLS)
    assert "sk-uji" not in str(info.value)
    assert json.dumps(str(info.value))


# ---------------------------------------------------------- 429 rate limit
from datetime import datetime, timezone

from app.llm.campus import rate_limit_delay

NOW = datetime(2026, 10, 19, 15, 21, 0, tzinfo=timezone.utc)
GATEWAY_429 = ('{"error":{"message":"Rate limit exceeded for api_key: abc. Limit type: max_parallel_requests. '
               'Current limit: 2, Remaining: 0. Limit resets at: 2026-10-19 15:21:39 UTC"}}')


def test_delay_dari_limit_resets_at():
    assert rate_limit_delay(LLMHTTPError(429, GATEWAY_429), NOW) == 39.0


def test_delay_dari_retry_after_detik_didahulukan():
    assert rate_limit_delay(LLMHTTPError(429, GATEWAY_429, retry_after="5"), NOW) == 5.0


def test_delay_dari_retry_after_tanggal_http():
    exc = LLMHTTPError(429, "x", retry_after="Mon, 19 Oct 2026 15:21:20 GMT")
    assert rate_limit_delay(exc, NOW) == 20.0


@pytest.mark.parametrize("reset,expected", [("15:30:00", 60.0), ("15:20:00", 1.0)])
def test_delay_dibatasi_1_sampai_60(reset, expected):
    msg = f"Limit resets at: 2026-10-19 {reset} UTC"
    assert rate_limit_delay(LLMHTTPError(429, msg), NOW) == expected


@pytest.mark.parametrize("exc", [LLMHTTPError(429, "tanpa petunjuk"), LLMHTTPError(503, GATEWAY_429),
                                 ValueError("x"), None])
def test_tanpa_petunjuk_atau_bukan_429_pakai_jeda_biasa(exc):
    assert rate_limit_delay(exc, NOW) is None


def test_retry_429_menunggu_sesuai_petunjuk_lalu_berhasil():
    sleeps = []
    send = FakeSend(LLMHTTPError(429, "x", retry_after="7"), resp([call()]))
    llm = CampusLLM(CFG, send=send, wait=wait_none(), sleep=sleeps.append)
    r = llm.call_llm([], TOOLS)
    assert sleeps == [7.0] and r.usage.retries == 1


def test_retry_503_tetap_pakai_jeda_biasa():
    sleeps = []
    send = FakeSend(LLMHTTPError(503, "down"), resp([call()]))
    CampusLLM(CFG, send=send, wait=wait_none(), sleep=sleeps.append).call_llm([], TOOLS)
    assert sleeps == [0]


# ---------------------------------------------------------- timeout
def test_timeout_dari_config_dipakai_transport():
    seen = []

    def send(cfg, messages, tools=None, **_):
        seen.append(cfg.timeout_s)
        return resp([call()]), 0.0

    CampusLLM(Config(**{**CFG.__dict__, "llm_timeout_s": 150.0}), send=send).call_llm([], TOOLS)
    assert seen == [150.0]


def test_retry_setelah_timeout_menunggu_60_detik():
    sleeps = []
    send = FakeSend(LLMHTTPError(None, "Timeout setelah 120 detik", timed_out=True), resp([call()]))
    CampusLLM(CFG, send=send, wait=wait_none(), sleep=sleeps.append).call_llm([], TOOLS)
    assert sleeps == [60.0]


def test_pesan_error_memuat_riwayat_percobaan():
    send = FakeSend(LLMHTTPError(None, "Timeout", timed_out=True),
                    *[LLMHTTPError(429, "Limit resets at: 2000-01-01 00:00:00 UTC")] * 3)
    llm = CampusLLM(CFG, send=send, wait=wait_none(), sleep=lambda s: None)
    with pytest.raises(LLMUnavailableError, match="timeout → HTTP 429 → HTTP 429 → HTTP 429"):
        llm.call_llm([], TOOLS)
