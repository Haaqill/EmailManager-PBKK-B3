from __future__ import annotations

import sqlite3
import threading

import pytest

from app.server.registry import BatchRegistry

STATUSES = [
    "queued",
    "scanning",
    "classifying",
    "drafting",
    "awaiting_review",
    "executing",
    "done",
    "failed",
    "cancelled",
]


def test_rekonsiliasi_mengubah_batch_aktif_menjadi_failed(tmp_path):
    database = tmp_path / "registry.sqlite"
    registry = BatchRegistry(database)
    batch_ids = {}
    for status in STATUSES:
        batch_id = registry.create_batch("user-1", 3)
        batch_ids[status] = batch_id
        if status != "queued":
            assert registry.transition(batch_id, ["queued"], status)
    registry.close()

    restarted = BatchRegistry(database)
    assert restarted.reconcile_on_start() == 6
    for status, batch_id in batch_ids.items():
        batch = restarted.get(batch_id, "user-1")
        assert batch is not None
        assert batch["status"] == (
            "failed" if status in STATUSES[:6] else status
        )
    restarted.close()


def test_hasil_executing_dipertahankan_dan_item_lain_dilewati(tmp_path):
    database = tmp_path / "registry.sqlite"
    registry = BatchRegistry(database)
    batch_id = registry.create_batch("user-1", 3)
    registry.set_plan(batch_id, ["i_ok", "i_pending", "i_reject"], 1)
    registry.save_decisions(
        batch_id,
        {"i_ok": "approve", "i_pending": "approve", "i_reject": "reject"},
    )
    assert registry.transition(batch_id, ["queued"], "executing")
    registry.record_item_result(
        batch_id, "i_ok", "ok", ["Kategori/Tugas"], True, "draft-1", 2, 0
    )
    registry.close()

    restarted = BatchRegistry(database)
    restarted.reconcile_on_start()
    report = restarted.build_report(batch_id)

    assert [item["status"] for item in report["results"]] == [
        "ok",
        "skipped",
        "rejected",
    ]
    assert report["summary"] == {
        "approved": 2,
        "rejected": 1,
        "actions_ok": 2,
        "actions_failed": 0,
    }
    restarted.close()


def test_hasil_gagal_masuk_ke_report_dan_ringkasan_aksi(tmp_path):
    registry = BatchRegistry(tmp_path / "registry.sqlite")
    batch_id = registry.create_batch("user-1", 1)
    registry.set_plan(batch_id, ["i_failed"], 1)
    registry.save_decisions(batch_id, {"i_failed": "approve"})
    registry.record_item_result(
        batch_id, "i_failed", "failed", [], False, None, 1, 2
    )

    report = registry.build_report(batch_id)

    assert report["results"][0]["status"] == "failed"
    assert report["summary"] == {
        "approved": 1,
        "rejected": 0,
        "actions_ok": 1,
        "actions_failed": 2,
    }
    registry.close()


def test_batch_milik_pengguna_lain_tidak_ditemukan(tmp_path):
    registry = BatchRegistry(tmp_path / "registry.sqlite")
    batch_id = registry.create_batch("user-1", 1)

    assert registry.get(batch_id, "user-2") is None
    registry.close()


def test_transition_hanya_berhasil_bila_status_sesuai(tmp_path):
    registry = BatchRegistry(tmp_path / "registry.sqlite")
    batch_id = registry.create_batch("user-1", 1)

    assert not registry.transition(batch_id, ["scanning"], "classifying")
    assert registry.transition(batch_id, ["queued"], "scanning")
    assert not registry.transition(batch_id, ["queued"], "classifying")

    for terminal in ("done", "failed", "cancelled"):
        terminal_id = registry.create_batch("user-1", 1)
        assert registry.transition(terminal_id, ["queued"], terminal)
        assert not registry.transition(terminal_id, [terminal], "scanning")
    registry.close()


def test_satu_transisi_menang_dalam_dua_thread(tmp_path):
    registry = BatchRegistry(tmp_path / "registry.sqlite")
    batch_id = registry.create_batch("user-1", 1)
    start = threading.Barrier(3)
    results = []

    def transition(to_status: str) -> None:
        start.wait()
        results.append(registry.transition(batch_id, ["queued"], to_status))

    threads = [
        threading.Thread(target=transition, args=("scanning",)),
        threading.Thread(target=transition, args=("classifying",)),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
    assert registry.get(batch_id, "user-1")["status"] in {
        "scanning",
        "classifying",
    }
    registry.close()


def test_skema_persistensi_hanya_memiliki_kolom_yang_diizinkan(tmp_path):
    database = tmp_path / "registry.sqlite"
    registry = BatchRegistry(database)
    batch_id = registry.create_batch("user-1", 1)
    registry.set_plan(batch_id, ["i_1"], 1)
    registry.record_item_result(
        batch_id,
        "i_1",
        "ok",
        ["RAHASIA-CANARY"],
        False,
        "RAHASIA-CANARY",
        1,
        0,
    )
    registry.close()

    connection = sqlite3.connect(database)
    try:
        batch_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(batches)")
        ]
        item_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(batch_items)")
        ]
        assert batch_columns == [
            "batch_id",
            "user_id",
            "status",
            "plan_version",
            "max_results",
            "created_at",
            "updated_at",
        ]
        assert item_columns == [
            "batch_id",
            "item_id",
            "decision",
            "status",
            "labels",
            "archived",
            "draft_id",
            "actions_ok",
            "actions_failed",
        ]
    finally:
        connection.close()


def test_report_menolak_batch_yang_tidak_dikenal(tmp_path):
    registry = BatchRegistry(tmp_path / "registry.sqlite")

    with pytest.raises(LookupError):
        registry.build_report("b_unknown")

    registry.close()
