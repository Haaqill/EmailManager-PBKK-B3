"""Tes logika tabel review (tanpa Streamlit)."""
from __future__ import annotations

import pytest

from app.contracts import PlanItem
from app.privacy.redact import pii_map_for, redact, release_pii_map
from app.ui.review import plan_to_rows, report_lines, rows_to_decisions


@pytest.fixture
def setup():
    peta = pii_map_for("ui-test")
    redact("Dr. Sari Wulandari <sari.w@univ.ac.id>", peta)
    plan = [
        PlanItem(thread_id="t1", summary=redact("Tugas dari Sari Wulandari", peta), category="Tugas",
                 priority="Mendesak", action="keep", needs_reply=True,
                 draft_body=redact("Terima kasih Sari Wulandari", peta), reason="tenggat"),
        PlanItem(thread_id="t2", summary="Promo", category="Promosi", priority="Nanti",
                 action="archive", needs_reply=False, reason="iklan"),
    ]
    yield plan, peta
    release_pii_map("ui-test")


def test_tampilan_sudah_direstore(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    assert "Sari Wulandari" in rows[0]["ringkasan"] and "Sari Wulandari" in rows[0]["draft"]
    assert "<PERSON_" in plan[0].summary


def test_approved_dan_rejected(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    rows[1]["setujui"] = False
    d = rows_to_decisions(rows, plan, peta)
    assert [(x.thread_id, x.status) for x in d] == [("t1", "approved"), ("t2", "rejected")]


def test_edit_kategori_menjadi_edited(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    rows[0]["kategori"] = "Akademik"
    d = rows_to_decisions(rows, plan, peta)[0]
    assert d.status == "edited" and d.edited.category == "Akademik"
    assert d.edited.draft_body == plan[0].draft_body          # draft tidak diubah → tetap teredaksi


def test_draft_diedit_diredaksi_ulang(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    rows[0]["draft"] = "Baik Sari Wulandari, saya kirim ke sari.w@univ.ac.id"
    d = rows_to_decisions(rows, plan, peta)[0]
    assert "Wulandari" not in d.edited.draft_body and "sari.w@" not in d.edited.draft_body


def test_draft_dikosongkan_tidak_perlu_balas(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    rows[0]["draft"] = None                                   # sel kosong dari data_editor
    d = rows_to_decisions(rows, plan, peta)[0]
    assert d.edited.draft_body is None and d.edited.needs_reply is False


def test_edit_melanggar_kontrak_ditolak(setup):
    plan, peta = setup
    rows = plan_to_rows(plan, peta)
    rows[1]["prioritas"] = "Mendesak"                         # Promosi harus Nanti
    with pytest.raises(ValueError, match="t2"):
        rows_to_decisions(rows, plan, peta)


def test_report_lines():
    lines = report_lines({"approved": 2, "rejected": 1, "planned": 3, "threads": 3, "actions_ok": 4,
                          "actions_failed": 0, "per_tool": {"label_thread": {"ok": 2, "gagal": 0}}})
    assert lines[0].startswith("2 thread disetujui") and "label_thread" in lines[-1]
