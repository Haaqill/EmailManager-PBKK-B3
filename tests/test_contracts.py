"""Tes untuk kontrak data bersama Tahap 1."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import (
    ActionRecord,
    DatasetMessage,
    DatasetRow,
    ErrorCode,
    PlanItem,
    ReviewDecision,
    ToolResult,
)


def _plan(**overrides) -> PlanItem:
    values = {
        "thread_id": "t1",
        "summary": "Informasi tugas",
        "category": "Tugas",
        "priority": "Normal",
        "action": "keep",
        "needs_reply": False,
        "reason": "Perlu diperiksa",
    }
    values.update(overrides)
    return PlanItem(**values)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("category", "Lainnya"),
        ("priority", "Rendah"),
        ("action", "delete"),
    ],
)
def test_plan_item_menolak_nilai_di_luar_kontrak(field, invalid):
    with pytest.raises(ValidationError):
        _plan(**{field: invalid})


@pytest.mark.parametrize("category", ["Promosi", "Spam"])
@pytest.mark.parametrize("priority", ["Mendesak", "Normal"])
def test_promosi_dan_spam_hanya_boleh_prioritas_nanti(category, priority):
    with pytest.raises(ValidationError):
        _plan(category=category, priority=priority)


def test_plan_item_menerima_semua_kategori_prioritas_dan_aksi_yang_diizinkan():
    for category in ("Akademik", "Tugas", "Pengumuman", "Pribadi", "Promosi", "Spam"):
        for priority in ("Mendesak", "Normal", "Nanti"):
            if category in ("Promosi", "Spam") and priority != "Nanti":
                continue
            for action in ("keep", "archive", "trash"):
                assert _plan(category=category, priority=priority, action=action)


def test_reason_dibatasi_maksimal_200_karakter():
    assert _plan(reason="x" * 200)
    with pytest.raises(ValidationError):
        _plan(reason="x" * 201)


def test_kebutuhan_balasan_mewajibkan_draft_dan_sebaliknya_tidak():
    assert _plan(needs_reply=False, draft_body=None)
    assert _plan(needs_reply=True, draft_body="Baik, terima kasih.")
    with pytest.raises(ValidationError):
        _plan(needs_reply=True, draft_body="")


def test_review_decision_memvalidasi_status_dan_item_edit():
    assert ReviewDecision(thread_id="t1", status="approved")
    assert ReviewDecision(thread_id="t1", status="rejected")
    assert ReviewDecision(thread_id="t1", status="edited", edited=_plan())
    with pytest.raises(ValidationError):
        ReviewDecision(thread_id="t1", status="edited")
    with pytest.raises(ValidationError):
        ReviewDecision(thread_id="t1", status="approved", edited=_plan())
    with pytest.raises(ValidationError):
        ReviewDecision(thread_id="t2", status="edited", edited=_plan())


def test_tool_result_mensyaratkan_error_code_hanya_untuk_gagal():
    assert ToolResult.sukses({"id": "t1"}).ok
    assert ToolResult.gagal(ErrorCode.NOT_FOUND, "Thread tidak ditemukan").error_code == ErrorCode.NOT_FOUND
    with pytest.raises(ValidationError):
        ToolResult(ok=True, error_code=ErrorCode.INTERNAL)
    with pytest.raises(ValidationError):
        ToolResult(ok=False)


def test_action_record_dan_dataset_message_mengikuti_bentuk_kontrak():
    record = ActionRecord(thread_id="t1", tool="archive_thread", ok=False, error_code=ErrorCode.NOT_FOUND)
    assert record.error_code == ErrorCode.NOT_FOUND
    message = DatasetMessage.model_validate(
        {"from": "sender@example.test", "to": "user@example.test", "date": "2026-10-18T10:00:00Z", "body": "Halo"}
    )
    assert message.from_ == "sender@example.test"
    assert message.model_dump(by_alias=True)["from"] == "sender@example.test"


def test_dataset_row_menolak_thread_tanpa_pesan():
    with pytest.raises(ValidationError):
        DatasetRow(
            id="t1",
            lang="id",
            unread=True,
            labels=[],
            subject="Subjek",
            messages=[],
            expected={
                "category": "Tugas",
                "priority": "Normal",
                "needs_reply": False,
                "action": "keep",
            },
        )
