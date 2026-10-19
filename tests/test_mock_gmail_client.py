"""Tes MockGmailAPIClient di atas eval/dataset.json."""
from __future__ import annotations

import json

import pytest

from app.gmail.mock_client import MockGmailAPIClient, load_dataset

DATASET = "eval/dataset.json"


def scan(c, **kw):
    args = {"unread_only": True, "newer_than_days": 7, "in_inbox": True, "sender_domain": "", "max_results": 50}
    return c.list_threads(**{**args, **kw})


def test_dataset_10_thread_valid_dan_lengkap():
    rows = load_dataset(DATASET)
    assert len(rows) == 10 and len({r.id for r in rows}) == 10
    assert {r.expected.category for r in rows} == {"Akademik", "Tugas", "Pengumuman", "Pribadi", "Promosi", "Spam"}
    assert {r.expected.priority for r in rows} == {"Mendesak", "Normal", "Nanti"}
    assert {r.lang for r in rows} == {"id", "en"}


def test_list_threads_dan_filter():
    c = MockGmailAPIClient(DATASET)
    threads = scan(c)
    assert len(threads) == 10
    assert threads[0].from_domain == "univ.ac.id" and threads[0].has_attachments
    assert [t.thread_id for t in scan(c, sender_domain="robotics-club.org")] == ["t009"]
    assert len(scan(c, max_results=3)) == 3


def test_label_diganti_tidak_menumpuk():
    c = MockGmailAPIClient(DATASET)
    c.apply_labels(thread_id="t001", category="Tugas", priority="Normal", reason="x")
    r = c.apply_labels(thread_id="t001", category="Akademik", priority="Mendesak", reason="x")
    assert r.removed == ["Kategori/Tugas", "Prioritas/Normal"]
    assert c.labels["t001"] == ["INBOX", "Kategori/Akademik", "Prioritas/Mendesak"]


def test_arsip_menghapus_inbox_dan_keluar_dari_scan():
    c = MockGmailAPIClient(DATASET)
    c.archive(thread_id="t005")
    assert "INBOX" not in c.labels["t005"]
    assert "t005" not in [t.thread_id for t in scan(c)]


def test_draft_memakai_header_thread():
    c = MockGmailAPIClient(DATASET)
    r = c.create_draft(thread_id="t002", body="Bisa, Pak.")
    assert r.draft_id == "draft-1"
    assert c.drafts[0]["to"].endswith("<budi.santoso@univ.ac.id>")
    assert c.drafts[0]["subject"] == "Re: Konfirmasi jadwal bimbingan skripsi"


def test_thread_tidak_ada():
    c = MockGmailAPIClient(DATASET)
    for call in (lambda: c.get_thread(thread_id="t999", max_messages=5),
                 lambda: c.archive(thread_id="t999")):
        with pytest.raises(LookupError):
            call()


def test_objek_tunggal_diterima(tmp_path):
    row = json.loads(open(DATASET, encoding="utf-8").read())[0]
    path = tmp_path / "satu.json"
    path.write_text(json.dumps(row), encoding="utf-8")
    assert list(MockGmailAPIClient(path).rows) == ["t001"]
