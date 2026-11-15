"""End-to-end tanpa jaringan: DatasetLLM + MockGmailAPIClient + InboxGraph + logika UI."""
from __future__ import annotations

import pytest

from app.agent import dispatcher as d
from app.agent.graph import InboxGraph
from app.gmail.mock_client import MockGmailAPIClient, load_dataset
from app.llm.mock import DatasetLLM
from app.privacy.redact import pii_map_for
from app.ui.review import plan_to_rows, rows_to_decisions

DATASET = "eval/dataset.json"


@pytest.fixture(autouse=True)
def _registry_bersih():
    d.clear_registry()
    yield
    d.clear_registry()


def test_dataset_valid_dan_mencakup_semua_label():
    rows = load_dataset(DATASET)                      # validasi DatasetRow + id unik
    assert {r.expected.category for r in rows} == {"Akademik", "Tugas", "Pengumuman", "Pribadi", "Promosi", "Spam"}
    assert {r.expected.priority for r in rows} == {"Mendesak", "Normal", "Nanti"}
    assert {r.lang for r in rows} == {"id", "en"}


def test_demo_batch_semua_disetujui():
    expected = {r.id: r.expected for r in load_dataset(DATASET)}
    gmail = MockGmailAPIClient(DATASET)
    llm = DatasetLLM(DATASET)
    graph = InboxGraph(llm, gmail)

    plan = graph.start("demo-1")
    assert len(plan) == len(expected) and graph.get_errors("demo-1") == []
    for p in plan:
        e = expected[p.thread_id]
        assert (p.category, p.priority, p.action, p.needs_reply) == (e.category, e.priority, e.action, e.needs_reply)

    peta = pii_map_for("demo-1")
    decisions = rows_to_decisions(plan_to_rows(plan, peta), plan, peta)
    report = graph.resume("demo-1", decisions)

    assert report["approved"] == len(expected) and report["actions_failed"] == 0
    assert report["per_tool"]["label_thread"]["ok"] == len(expected)
    archived = {t for t, row in gmail._threads.items() if "INBOX" not in row.labels}
    assert archived == {t for t, e in expected.items() if e.action == "archive"}
    assert sorted(x["thread_id"] for x in gmail.drafts) == sorted(t for t, e in expected.items() if e.needs_reply)
    prompts = str([c["messages"] for c in llm.calls])
    assert "sari.w@univ.ac.id" not in prompts and "0812-3456-7890" not in prompts
