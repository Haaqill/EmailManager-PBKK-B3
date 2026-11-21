"""Tes skrip evaluasi confidence (eval/metrics.py, eval/run_eval.py). Tanpa jaringan."""
from __future__ import annotations

import json

import pytest

from app.agent import dispatcher as d
from app.gmail.mock_client import load_dataset
from app.llm.mock import MockLLM, make_text_response, make_tool_response
from eval.metrics import NO_LEVEL, Record, compare, monotonic, stability, summarize
from eval.run_eval import main, run_once

DATASET = "eval/dataset.json"
EXP = {"category": "Tugas", "priority": "Mendesak", "action": "keep", "needs_reply": False}


@pytest.fixture(autouse=True)
def _registry_bersih():
    d.clear_registry()
    yield
    d.clear_registry()


def _rec(level, cat_ok=True, act_ok=True, *, tid="t", injection=False, classified=True):
    return Record(thread_id=tid, is_injection=injection, classified=classified,
                  confidence=level, category_ok=cat_ok, action_ok=act_ok,
                  predicted={"category": "x" if cat_ok else "y"}, expected={})


def _cls(tid, category, priority, action, confidence, needs_reply=False):
    return make_tool_response("submit_classification", {
        "thread_id": tid, "summary": "ringkasan", "category": category, "priority": priority,
        "action": action, "needs_reply": needs_reply, "reason": "alasan",
        "confidence": confidence,
    })


# ------------------------------------------------------------------ compare
def test_compare_benar_semua():
    r = compare("t001", {**EXP, "confidence": "tinggi"}, EXP)
    assert r.classified and r.both_ok and r.priority_ok and r.needs_reply_ok
    assert r.level == "tinggi"


def test_compare_kategori_salah_aksi_benar():
    r = compare("t001", {**EXP, "category": "Akademik", "confidence": "sedang"}, EXP)
    assert not r.category_ok and r.action_ok and not r.both_ok


def test_compare_gagal_dan_confidence_tidak_valid():
    assert compare("t001", None, EXP).classified is False
    r = compare("t001", {**EXP, "confidence": "yakin"}, EXP)
    assert r.confidence is None and r.level == NO_LEVEL


def test_compare_tidak_menyimpan_summary_atau_reason():
    r = compare("t001", {**EXP, "summary": "RAHASIA", "reason": "RAHASIA"}, EXP)
    assert "RAHASIA" not in json.dumps(r.to_dict())


# ------------------------------------------------------------------ summarize
def test_summarize_menghitung_per_level():
    s = summarize([
        _rec("tinggi"), _rec("tinggi"), _rec("tinggi", cat_ok=False),
        _rec("sedang", act_ok=False), _rec("sedang"),
        _rec("rendah", cat_ok=False, injection=True),
        _rec(None),
        _rec(None, classified=False),
    ])
    assert (s["threads"], s["classified"], s["failed"], s["confidence_missing"]) == (8, 7, 1, 1)
    t, se, re_ = (s["by_level"][lv] for lv in ("tinggi", "sedang", "rendah"))
    assert (t["n"], t["category"], t["action"], t["both"]) == (3, 0.6667, 1.0, 0.6667)
    assert (se["n"], se["both"]) == (2, 0.5)
    assert (re_["n"], re_["both"], re_["injection_n"]) == (1, 0.0, 1)
    assert s["overall"]["n"] == 7
    assert s["monotonic_both"] is True


def test_monotonic():
    lv = lambda *rates: {k: {"n": 1 if r is not None else 0, "both": r}
                         for k, r in zip(("tinggi", "sedang", "rendah"), rates)}
    assert monotonic(lv(1.0, 0.5, 0.5)) is True
    assert monotonic(lv(0.5, 1.0, 0.0)) is False
    assert monotonic(lv(0.4, None, 0.9)) is False      # level kosong dilewati
    assert monotonic(lv(1.0, None, None)) is None
    assert monotonic(lv(None, None, None)) is None


def test_stability():
    a = [_rec("tinggi", tid="t1"), _rec("sedang", tid="t2"), _rec("rendah", tid="t3")]
    b = [_rec("tinggi", tid="t1"), _rec("rendah", tid="t2"),
         _rec(None, tid="t3", classified=False)]
    st = stability([a, b])
    assert st["threads"] == 2                 # t3 gagal di satu putaran
    assert st["same_level"] == 0.5
    assert st["same_labels"] == 1.0
    assert st["per_thread"]["t2"] == ["sedang", "rendah"]
    assert stability([a])["same_level"] is None


# ------------------------------------------------------------------ run_once (MockLLM)
def test_run_once_memakai_node_classify_dan_menilai_label():
    llm = MockLLM([
        _cls("t001", "Tugas", "Mendesak", "keep", "tinggi"),        # benar
        _cls("t006", "Promosi", "Nanti", "archive", "rendah"),      # kategori salah (Spam)
        *[make_text_response("bukan tool")] * 3,                   # t007: gagal setelah koreksi
    ])
    recs = {r.thread_id: r for r in run_once(llm, DATASET, "eval-tes", ["t001", "t006", "t007"])}

    assert recs["t001"].both_ok and recs["t001"].level == "tinggi"
    assert not recs["t006"].category_ok and recs["t006"].action_ok
    assert recs["t006"].level == "rendah"
    assert recs["t007"].classified is False and recs["t007"].is_injection is True
    assert llm.remaining == 0
    # Hanya klasifikasi: tidak ada tool draf atau aksi Gmail.
    names = {t["function"]["name"] for c in llm.calls for t in c["tools"]}
    assert names == {"submit_classification"}


def test_run_once_mengirim_teks_teredaksi_ke_llm():
    address = "sari.w@univ.ac.id"   # pengirim t001 di dataset
    llm = MockLLM([_cls("t001", "Tugas", "Mendesak", "keep", "tinggi")])
    run_once(llm, DATASET, "eval-redaksi", ["t001"])
    sent = json.dumps(llm.calls[0]["messages"], ensure_ascii=False)
    assert address not in sent


# ------------------------------------------------------------------ main
def test_main_mock_tidak_mencetak_isi_email(tmp_path, capsys):
    out = tmp_path / "hasil.json"
    assert main(["--backend", "mock", "--runs", "2", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    saved = out.read_text(encoding="utf-8")
    for row in load_dataset(DATASET):
        for m in row.messages:
            snippet = m.body[:30]
            assert snippet not in printed and snippet not in saved
        assert row.subject not in printed and row.subject not in saved
    result = json.loads(saved)
    assert result["combined"]["classified"] == 20
    assert result["stability"]["same_level"] == 1.0
    assert "bukan kualitas klasifikasi" in printed


def test_main_runs_minimal_satu():
    with pytest.raises(SystemExit):
        main(["--runs", "0"])
