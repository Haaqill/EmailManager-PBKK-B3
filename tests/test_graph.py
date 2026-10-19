"""Tes workflow InboxGraph dengan MockLLM dan Gmail palsu (gate M2)."""
from __future__ import annotations

import json

import pytest

from app.agent import dispatcher as d
from app.agent.graph import InboxGraph
from app.contracts import LLMUnavailableError, PlanItem, ReviewDecision
from app.llm.mock import MockLLM, make_tool_response
from tests.test_gmail_tools import MockGmail

# (id, kategori, prioritas, aksi, perlu_balas)
THREADS = [
    ("t01", "Tugas", "Mendesak", "keep", True),
    ("t02", "Akademik", "Normal", "keep", True),
    ("t03", "Pengumuman", "Normal", "archive", False),
    ("t04", "Pribadi", "Normal", "keep", True),
    ("t05", "Promosi", "Nanti", "archive", False),
    ("t06", "Spam", "Nanti", "archive", False),
    ("t07", "Akademik", "Mendesak", "keep", False),
    ("t08", "Tugas", "Normal", "keep", False),
    ("t09", "Pengumuman", "Nanti", "archive", False),
    ("t10", "Promosi", "Nanti", "archive", False),
]


@pytest.fixture(autouse=True)
def _registry_bersih():
    d.clear_registry()
    yield
    d.clear_registry()


@pytest.fixture
def gmail() -> MockGmail:
    g = MockGmail()
    for tid, *_ in THREADS:
        sender = "Dr. Sari Wulandari <sari.w@univ.ac.id>" if tid == "t01" else f"Info {tid} <info@{tid}.ac.id>"
        g.tambah_thread(
            tid, subject=f"Subjek {tid}", from_domain="univ.ac.id" if tid == "t01" else f"{tid}.ac.id",
            snippet="ringkas",
            messages=[{"from": sender, "date": "2026-10-13T08:15:00+07:00",
                       "body": f"Halo, ini pesan {tid}. Hubungi sari.w@univ.ac.id jika perlu."}],
        )
    return g


def classification(tid, cat, pri, act, reply):
    return make_tool_response("submit_classification", {
        "thread_id": tid, "summary": f"Ringkasan {tid}", "category": cat, "priority": pri,
        "action": act, "needs_reply": reply, "reason": "uji"})


def draft(tid, body):
    return make_tool_response("submit_draft", {"thread_id": tid, "body": body})


def full_batch_llm() -> MockLLM:
    items = [classification(*t) for t in THREADS]
    items += [draft("t01", "Terima kasih <PERSON_1>, tugas akan saya kumpulkan."),
              draft("t02", "Baik, terima kasih."), draft("t04", "Siap, sampai jumpa.")]
    return MockLLM(items)


def test_batch_10_thread_sampai_laporan(gmail):
    llm = full_batch_llm()
    graph = InboxGraph(llm, gmail)

    plan = graph.start("b1")
    assert len(plan) == 10 and all(isinstance(p, PlanItem) for p in plan)
    assert [p.thread_id for p in plan if p.needs_reply] == ["t01", "t02", "t04"]
    assert gmail.labels_applied == [] and gmail.drafts == []      # belum ada aksi sebelum review

    t08 = next(p for p in plan if p.thread_id == "t08")
    decisions = [ReviewDecision(thread_id=f"t0{i}", status="approved") for i in range(1, 8)]
    decisions.append(ReviewDecision(thread_id="t08", status="edited",
                                    edited=t08.model_copy(update={"category": "Akademik", "action": "archive"})))
    decisions.append(ReviewDecision(thread_id="t09", status="rejected"))   # t10 tanpa keputusan → rejected
    report = graph.resume("b1", decisions)

    assert (report["threads"], report["planned"], report["approved"], report["rejected"]) == (10, 10, 8, 2)
    assert report["actions_failed"] == 0 and report["errors"] == []
    labelled = {x["thread_id"]: x["applied"] for x in gmail.labels_applied}
    assert set(labelled) == {f"t0{i}" for i in range(1, 9)}
    assert labelled["t08"] == ["Kategori/Akademik", "Prioritas/Normal"]     # nilai hasil edit
    assert sorted(gmail.archived) == ["t03", "t05", "t06", "t08"]
    assert [x["thread_id"] for x in gmail.drafts] == ["t01", "t02", "t04"]


def test_thread_ditolak_tidak_tersentuh(gmail):
    graph = InboxGraph(full_batch_llm(), gmail)
    graph.start("b2")
    report = graph.resume("b2", [])                                        # semua ditolak
    assert report["rejected"] == 10 and report["actions_ok"] == 0
    assert gmail.labels_applied == [] and gmail.archived == [] and gmail.drafts == []
    state = graph.graph.get_state(graph._config("b2")).values
    assert state["action_history"] == []


def test_llm_tidak_melihat_pii_dan_draft_dipulihkan(gmail):
    llm = full_batch_llm()
    graph = InboxGraph(llm, gmail)
    graph.start("b3")
    graph.resume("b3", [ReviewDecision(thread_id="t01", status="approved")])

    prompts = json.dumps([c["messages"] for c in llm.calls])
    assert "sari.w@univ.ac.id" not in prompts and "Wulandari" not in prompts
    assert "Sari Wulandari" in gmail.drafts[0]["body"]                     # restore sebelum ke Gmail


def test_state_checkpoint_tanpa_pii(gmail):
    graph = InboxGraph(full_batch_llm(), gmail)
    graph.start("b4")
    values = json.dumps(graph.graph.get_state(graph._config("b4")).values, default=str)
    assert "sari.w@univ.ac.id" not in values and "Wulandari" not in values


def test_isi_email_dibungkus(gmail, monkeypatch):
    import app.agent.prompts as prompts
    monkeypatch.setattr(prompts, "wrap_email_content", lambda t: f"<email_content>{t}</email_content>")
    llm = full_batch_llm()
    InboxGraph(llm, gmail).start("b5")
    user_msg = llm.calls[0]["messages"][1]["content"]
    assert "<email_content>" in user_msg and "Subjek t01" in user_msg.split("<email_content>")[0]


def test_klasifikasi_tidak_valid_dikoreksi(gmail):
    items = [make_tool_response("submit_classification", {
        "thread_id": "t01", "summary": "x", "category": "Penting", "priority": "Normal",
        "action": "keep", "needs_reply": False, "reason": "x"})]
    items += [classification("t01", "Tugas", "Mendesak", "keep", False)]
    items += [classification(*t[:4], False) for t in THREADS[1:]]
    llm = MockLLM(items)
    plan = InboxGraph(llm, gmail).start("b6")
    assert len(plan) == 10
    koreksi = llm.calls[1]["messages"]
    assert koreksi[-1]["role"] == "tool" and "tidak valid" in koreksi[-1]["content"]


def test_klasifikasi_tetap_rusak_dilewati_batch_lanjut(gmail):
    rusak = make_tool_response("submit_classification", {"thread_id": "t01", "summary": "x"})
    items = [rusak, rusak, rusak] + [classification(*t[:4], False) for t in THREADS[1:]]
    graph = InboxGraph(MockLLM(items), gmail)
    plan = graph.start("b7")
    assert [p.thread_id for p in plan] == [t[0] for t in THREADS[1:]]
    assert graph.get_errors("b7")[0]["thread_id"] == "t01"


def test_thread_id_dari_llm_tidak_dipercaya(gmail):
    items = [make_tool_response("submit_classification", {
        "thread_id": "t99", "summary": "x", "category": "Tugas", "priority": "Normal",
        "action": "keep", "needs_reply": False, "reason": "x"})]
    items += [classification(*t[:4], False) for t in THREADS[1:]]
    plan = InboxGraph(MockLLM(items), gmail).start("b8")
    assert plan[0].thread_id == "t01"


def test_llm_mati_diteruskan(gmail):
    graph = InboxGraph(MockLLM([LLMUnavailableError("server mati")]), gmail)
    with pytest.raises(LLMUnavailableError):
        graph.start("b9")
