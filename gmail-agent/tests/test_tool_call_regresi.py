"""Regresi: 'keluaran tetap tidak valid setelah 2 koreksi: tool submit_classification tidak dipanggil'."""
from __future__ import annotations

import pytest
from tenacity import wait_none

from app.agent.graph import InboxGraph, _same_tool
from app.agent.prompts import SUBMIT_CLASSIFICATION_TOOL, ClassificationOutput, SYSTEM_CLASSIFY
from app.config import Config
from app.contracts import LLMOutputError
from app.llm.campus import CampusLLM
from app.llm.mock import DatasetLLM, MockLLM, make_text_response, make_tool_response
from app.llm.transport import LLMHTTPError

THREAD = {"thread_id": "1a1676caf1826719", "subject": "Halo", "from_domain": "x.ac.id",
          "attachments": [], "messages": [{"from": "a", "date": "d", "body_text": "isi"}]}
ARGS = {"thread_id": "1a1676caf1826719", "summary": "s", "category": "Tugas", "priority": "Normal",
        "action": "keep", "needs_reply": False, "reason": "r"}
CFG = Config(llm_backend="campus", llm_api_style="openai", llm_tool_mode="native",
             llm_base_url="https://llm.kampus.ac.id/v1", llm_api_key="sk-uji-123456",
             llm_model="m", eval_dataset_path="eval/dataset.json")


def _ask(llm):
    g = InboxGraph.__new__(InboxGraph)
    g.llm = llm
    errors: list[dict] = []
    out = g._ask(SYSTEM_CLASSIFY, THREAD, SUBMIT_CLASSIFICATION_TOOL, ClassificationOutput, "classify", errors)
    return out, errors


def test_dataset_llm_thread_tak_dikenal_error_jelas():
    out, errors = _ask(DatasetLLM("eval/dataset.json"))
    assert out is None and len(errors) == 1
    assert "LLM_BACKEND=mock" in errors[0]["message"] and "campus" in errors[0]["message"]


@pytest.mark.parametrize("raw", ["functions.submit_classification", "default_api:submit_classification",
                                 "submit_classification:0", " Submit_Classification "])
def test_nama_tool_berawalan_diterima(raw):
    assert _same_tool(raw, "submit_classification")
    out, errors = _ask(MockLLM([make_tool_response(raw, ARGS)]))
    assert out is not None and errors == []


def test_pesan_error_menyebut_apa_yang_dikembalikan_llm():
    out, errors = _ask(MockLLM([make_tool_response("submit_draft", {"body": "x"})] * 3))
    assert out is None and "submit_draft" in errors[0]["message"]
    out, errors = _ask(MockLLM([make_text_response("Baik, akan saya balas.")] * 3))
    assert "hanya membalas teks" in errors[0]["message"]


def test_instruksi_eksplisit_di_pesan_user():
    llm = MockLLM([make_tool_response("submit_classification", ARGS)])
    _ask(llm)
    assert "panggil tool submit_classification" in llm.calls[0]["messages"][1]["content"]


# ---------------------------------------------------------------- CampusLLM
def _resp(message):
    return {"model": "m", "choices": [{"message": message}], "usage": {}}


class Send:
    def __init__(self, *items):
        self.items, self.kwargs = list(items), []

    def __call__(self, cfg, messages, tools=None, **extra):
        self.kwargs.append(extra)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, 0.0


def test_tool_choice_bernama_dikirim_untuk_satu_tool():
    send = Send(_resp({"content": None, "tool_calls": [{"id": "1", "function": {
        "name": "submit_classification", "arguments": "{}"}}]}))
    CampusLLM(CFG, send=send, wait=wait_none()).call_llm([], [SUBMIT_CLASSIFICATION_TOOL])
    assert send.kwargs[0]["tool_choice"]["function"]["name"] == "submit_classification"


def test_tool_choice_ditolak_gateway_diulang_tanpa_tool_choice():
    ok = _resp({"content": None, "tool_calls": [{"id": "1", "function": {
        "name": "submit_classification", "arguments": "{}"}}]})
    send = Send(LLMHTTPError(400, "tool_choice not supported"), ok, ok)
    llm = CampusLLM(CFG, send=send, wait=wait_none())
    llm.call_llm([], [SUBMIT_CLASSIFICATION_TOOL])
    llm.call_llm([], [SUBMIT_CLASSIFICATION_TOOL])
    assert "tool_choice" in send.kwargs[0] and send.kwargs[1] == {} and send.kwargs[2] == {}


@pytest.mark.parametrize("content", [
    '{"thread_id": "t", "summary": "s"}',
    '```json\n{"thread_id": "t", "summary": "s"}\n```',
    '<think>hmm</think><tool_call>{"name": "submit_classification", "arguments": {"thread_id": "t", "summary": "s"}}</tool_call>',
])
def test_tool_call_yang_ditulis_sebagai_teks_diselamatkan(content):
    send = Send(_resp({"content": content}))
    r = CampusLLM(CFG, send=send, wait=wait_none()).call_llm([], [SUBMIT_CLASSIFICATION_TOOL])
    assert r.tool_calls[0].name == "submit_classification"
    assert r.tool_calls[0].arguments == {"thread_id": "t", "summary": "s"}


def test_teks_biasa_tetap_error_setelah_dua_koreksi():
    send = Send(*[_resp({"content": "Baik, akan saya balas."})] * 3)
    with pytest.raises(LLMOutputError):
        CampusLLM(CFG, send=send, wait=wait_none()).call_llm([], [SUBMIT_CLASSIFICATION_TOOL])
