"""Tes confidence (tinggi/sedang/rendah) dari klasifikasi sampai kontrak Laravel.

confidence bukan gerbang keamanan: tes di bawah memastikan nilainya tidak mengubah
requires_confirmation maupun keputusan bawaan. Semua tanpa jaringan.
"""
from __future__ import annotations

import json
import re

import pytest

from app.agent import dispatcher as d
from app.agent.graph import InboxGraph
from app.agent.prompts import SUBMIT_CLASSIFICATION_TOOL, SYSTEM_CLASSIFY, ClassificationOutput
from app.contracts import CONFIDENCE_LEVELS
from app.gmail.mock_client import MockGmailAPIClient, load_dataset
from app.llm.mock import DatasetLLM, MockLLM, make_tool_response, mock_confidence
from app.privacy.contract import RawThreadMeta, build_plan_snapshot
from app.privacy.redact import PIIRedactor, pii_map_for, release_pii_map
from tests.test_graph import gmail  # noqa: F401  (fixture)

DATASET = "eval/dataset.json"
BASE = dict(thread_id="t", summary="s", category="Tugas", priority="Normal",
            action="keep", needs_reply=False, reason="r")


@pytest.fixture(autouse=True)
def _registry_bersih():
    d.clear_registry()
    yield
    d.clear_registry()


# ------------------------------------------------------------- ClassificationOutput
@pytest.mark.parametrize("raw, expected", [
    ("tinggi", "tinggi"), ("sedang", "sedang"), ("rendah", "rendah"),
    (" Tinggi ", "tinggi"), ("RENDAH", "rendah"),
])
def test_level_valid_diterima(raw, expected):
    assert ClassificationOutput(**BASE, confidence=raw).confidence == expected


@pytest.mark.parametrize("raw", [None, "", "yakin", "high", 0.9, 1, True, ["tinggi"], {"x": 1}])
def test_nilai_tidak_valid_menjadi_none_tanpa_gagal(raw):
    assert ClassificationOutput(**BASE, confidence=raw).confidence is None


def test_field_hilang_menjadi_none():
    assert ClassificationOutput(**BASE).confidence is None


def test_skema_llm_opsional_tanpa_anyof():
    params = SUBMIT_CLASSIFICATION_TOOL["function"]["parameters"]
    assert params["properties"]["confidence"]["enum"] == list(CONFIDENCE_LEVELS)
    assert "confidence" not in params["required"]
    assert "anyOf" not in json.dumps(params)


def test_prompt_memuat_rubrik_tanpa_angka():
    rubrik = SYSTEM_CLASSIFY.split("- confidence:", 1)[1].split("Tanggal dan domain", 1)[0]
    for level in CONFIDENCE_LEVELS:
        assert f"{level}:" in rubrik
    assert not re.search(r"\d", rubrik)
    # bagian lain prompt tetap ada
    assert "Placeholder seperti <PERSON_1>" in SYSTEM_CLASSIFY
    assert "Promosi dan Spam selalu Nanti" in SYSTEM_CLASSIFY


# ------------------------------------------------------------- graph
def _klasifikasi(tid, **extra):
    return make_tool_response("submit_classification", {
        "thread_id": tid, "summary": f"Ringkasan {tid}", "category": "Tugas", "priority": "Normal",
        "action": "keep", "needs_reply": False, "reason": "uji", **extra})


def test_confidence_hilang_atau_tidak_valid_dihitung_tanpa_menggagalkan_item(gmail):  # noqa: F811
    llm = MockLLM([
        _klasifikasi("t01", confidence="tinggi"),
        _klasifikasi("t02"),                       # hilang
        _klasifikasi("t03", confidence="pasti"),   # tidak valid
    ])
    graph = InboxGraph(llm, gmail)

    plan = graph.start("b-conf", batch_size=3)

    assert [p.confidence for p in plan] == ["tinggi", None, None]
    assert graph.get_errors("b-conf") == []
    assert len(llm.calls) == 3                     # tidak ada koreksi LLM gara-gara confidence
    report = graph.resume("b-conf", [])
    assert report["confidence_missing"] == 2
    assert "pasti" not in json.dumps(report)       # hanya jumlah yang dilaporkan


def test_alur_mock_ujung_ke_ujung_sampai_kontrak():
    rows = load_dataset(DATASET)
    gmail = MockGmailAPIClient(DATASET)
    graph = InboxGraph(DatasetLLM(DATASET), gmail)

    plan = graph.start("demo-conf")
    raws = {}
    for p in plan:
        t = gmail.get_thread(thread_id=p.thread_id, max_messages=5)
        raws[p.thread_id] = RawThreadMeta.model_validate({
            "thread_id": t.thread_id, "subject": t.subject, "from": t.messages[0].from_,
            "date": t.messages[0].date, "attachments": [a.model_dump() for a in t.attachments],
        })
    snap = build_plan_snapshot([p.model_dump() for p in plan], raws, pii_map_for("demo-conf"), 1)
    release_pii_map("demo-conf")

    got = {i.thread_id: i.confidence for i in snap.items}
    assert got == {r.id: mock_confidence(r.id) for r in rows}
    assert set(got.values()) == set(CONFIDENCE_LEVELS)   # ketiga tingkat, termasuk rendah
    assert graph.resume("demo-conf", [])["confidence_missing"] == 0


# ------------------------------------------------------------- bukan gerbang keamanan
@pytest.mark.parametrize("action, draft_body", [
    ("keep", None), ("archive", None), ("trash", None), ("keep", "Baik."), ("archive", "Baik."),
])
def test_confidence_tidak_mengubah_requires_confirmation_atau_isi_item(action, draft_body):
    raw = RawThreadMeta.model_validate({"thread_id": "t1", "subject": "S", "from": "A <a@b.ac.id>",
                                        "date": "2026-11-18"})
    hasil = {}
    for level in (*CONFIDENCE_LEVELS, None):
        item = {"thread_id": "t1", "summary": "s", "category": "Tugas", "priority": "Normal",
                "action": action, "needs_reply": draft_body is not None, "draft_body": draft_body,
                "reason": "r", "confidence": level}
        snap = build_plan_snapshot([item], {"t1": raw}, PIIRedactor(keep_domain=False), 1)
        dumped = snap.items[0].model_dump()
        assert dumped.pop("confidence") == level
        hasil[level] = dumped

    pertama = next(iter(hasil.values()))
    assert all(v == pertama for v in hasil.values())
    assert pertama["requires_confirmation"] == (action == "trash")


def test_confidence_tidak_mengubah_keputusan_bawaan(gmail):  # noqa: F811
    llm = MockLLM([_klasifikasi(f"t0{i}", confidence=lv)
                   for i, lv in enumerate(("tinggi", "sedang", "rendah"), start=1)])
    graph = InboxGraph(llm, gmail)
    graph.start("b-default", batch_size=3)

    report = graph.resume("b-default", [])         # tanpa keputusan pengguna

    assert report["approved"] == 0 and report["rejected"] == 3
    assert report["actions_ok"] == 0 and gmail.labels_applied == []
