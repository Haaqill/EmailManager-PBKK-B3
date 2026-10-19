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


def test_demo_10_thread_semua_disetujui():
    expected = {r.id: r.expected for r in load_dataset(DATASET)}
    gmail = MockGmailAPIClient(DATASET)
    llm = DatasetLLM(DATASET)
    graph = InboxGraph(llm, gmail)

    plan = graph.start("demo-1")
    assert len(plan) == 10 and graph.get_errors("demo-1") == []
    for p in plan:
        e = expected[p.thread_id]
        assert (p.category, p.priority, p.action, p.needs_reply) == (e.category, e.priority, e.action, e.needs_reply)

    peta = pii_map_for("demo-1")
    decisions = rows_to_decisions(plan_to_rows(plan, peta), plan, peta)
    report = graph.resume("demo-1", decisions)

    assert report["approved"] == 10 and report["actions_failed"] == 0
    assert len(gmail.labels_applied) == 10
    assert sorted(gmail.archived) == sorted(t for t, e in expected.items() if e.action == "archive")
    assert sorted(x["thread_id"] for x in gmail.drafts) == sorted(t for t, e in expected.items() if e.needs_reply)
    prompts = str([c["messages"] for c in llm.calls])
    assert "sari.w@univ.ac.id" not in prompts and "0812-3456-7890" not in prompts
