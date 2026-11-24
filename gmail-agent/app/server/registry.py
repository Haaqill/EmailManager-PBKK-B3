"""Registri batch SQLite tanpa menyimpan konten email atau data pribadi."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Iterable, Mapping, Sequence

_BATCH_STATUSES = {
    "queued",
    "scanning",
    "classifying",
    "drafting",
    "awaiting_review",
    "executing",
    "done",
    "failed",
    "cancelled",
}
_IN_PROGRESS_STATUSES = (
    "queued",
    "scanning",
    "classifying",
    "drafting",
    "awaiting_review",
    "executing",
)
_TERMINAL_STATUSES = {"done", "failed", "cancelled"}
_RESULT_STATUSES = {"ok", "failed", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchRegistry:
    """Simpan status batch dan hasil angka dengan satu koneksi thread-safe."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = path or os.getenv("AGENT_REGISTRY_PATH")
        if configured_path:
            self.path = Path(configured_path)
        else:
            self.path = Path(__file__).resolve().parents[2] / "agent_registry.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=DELETE")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    max_results INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batch_items (
                    batch_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    status TEXT,
                    labels TEXT NOT NULL,
                    archived INTEGER NOT NULL,
                    draft_id TEXT,
                    actions_ok INTEGER NOT NULL,
                    actions_failed INTEGER NOT NULL,
                    PRIMARY KEY (batch_id, item_id)
                );
                """
            )
            self._connection.commit()

    def close(self) -> None:
        """Tutup koneksi SQLite."""
        with self._lock:
            self._connection.close()

    def create_batch(self, user_id: str, max_results: int) -> str:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("ID pengguna tidak valid.")
        if type(max_results) is not int or not 1 <= max_results <= 10:
            raise ValueError("Jumlah hasil tidak valid.")

        batch_id = f"b_{secrets.token_hex(16)}"
        now = _now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO batches
                    (batch_id, user_id, status, plan_version, max_results, created_at, updated_at)
                VALUES (?, ?, 'queued', 1, ?, ?, ?)
                """,
                (batch_id, user_id, max_results, now, now),
            )
        return batch_id

    def get(self, batch_id: str, user_id: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM batches WHERE batch_id = ? AND user_id = ?",
                (batch_id, user_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def transition(
        self,
        batch_id: str,
        from_statuses: Iterable[str],
        to_status: str,
    ) -> bool:
        if to_status not in _BATCH_STATUSES:
            raise ValueError("Status batch tidak valid.")
        statuses = tuple(dict.fromkeys(from_statuses))
        if not statuses:
            return False
        if any(status not in _BATCH_STATUSES for status in statuses):
            raise ValueError("Status batch tidak valid.")

        eligible = tuple(status for status in statuses if status not in _TERMINAL_STATUSES)
        if not eligible:
            return False
        placeholders = ", ".join("?" for _ in eligible)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE batches
                SET status = ?, updated_at = ?
                WHERE batch_id = ? AND status IN ({placeholders})
                """,
                (to_status, _now(), batch_id, *eligible),
            )
        return cursor.rowcount == 1

    def set_plan(
        self, batch_id: str, item_ids: Sequence[str], plan_version: int
    ) -> None:
        if type(plan_version) is not int or plan_version < 1:
            raise ValueError("Versi plan tidak valid.")
        if any(not isinstance(item_id, str) or not item_id for item_id in item_ids):
            raise ValueError("ID item tidak valid.")
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("ID item tidak valid.")
        now = _now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE batches
                SET plan_version = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (plan_version, now, batch_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("Batch tidak ditemukan.")
            self._connection.execute(
                "DELETE FROM batch_items WHERE batch_id = ?", (batch_id,)
            )
            self._connection.executemany(
                """
                INSERT INTO batch_items
                    (batch_id, item_id, decision, status, labels, archived,
                     draft_id, actions_ok, actions_failed)
                VALUES (?, ?, 'none', NULL, '[]', 0, NULL, 0, 0)
                """,
                ((batch_id, item_id) for item_id in item_ids),
            )

    def save_decisions(self, batch_id: str, decisions: Mapping[str, str]) -> None:
        if any(decision not in {"approve", "reject"} for decision in decisions.values()):
            raise ValueError("Keputusan item tidak valid.")
        with self._lock, self._connection:
            for item_id, decision in decisions.items():
                cursor = self._connection.execute(
                    """
                    UPDATE batch_items
                    SET decision = ?
                    WHERE batch_id = ? AND item_id = ?
                    """,
                    (decision, batch_id, item_id),
                )
                if cursor.rowcount != 1:
                    raise LookupError("Item batch tidak ditemukan.")
            self._connection.execute(
                "UPDATE batches SET updated_at = ? WHERE batch_id = ?",
                (_now(), batch_id),
            )

    def record_item_result(
        self,
        batch_id: str,
        item_id: str,
        status: str,
        labels: Sequence[str],
        archived: bool,
        draft_id: str | None,
        actions_ok: int,
        actions_failed: int,
    ) -> None:
        if status not in _RESULT_STATUSES:
            raise ValueError("Status hasil tidak valid.")
        if not isinstance(labels, (list, tuple)) or any(
            not isinstance(label, str) for label in labels
        ):
            raise ValueError("Label hasil tidak valid.")
        if not isinstance(archived, bool):
            raise ValueError("Status arsip tidak valid.")
        if draft_id is not None and not isinstance(draft_id, str):
            raise ValueError("ID draf tidak valid.")
        if (
            type(actions_ok) is not int
            or actions_ok < 0
            or type(actions_failed) is not int
            or actions_failed < 0
        ):
            raise ValueError("Jumlah aksi tidak valid.")

        now = _now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE batch_items
                SET status = ?, labels = ?, archived = ?, draft_id = ?,
                    actions_ok = ?, actions_failed = ?
                WHERE batch_id = ? AND item_id = ?
                """,
                (
                    status,
                    json.dumps(list(labels)),
                    int(archived),
                    draft_id,
                    actions_ok,
                    actions_failed,
                    batch_id,
                    item_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError("Item batch tidak ditemukan.")
            self._connection.execute(
                "UPDATE batches SET updated_at = ? WHERE batch_id = ?",
                (now, batch_id),
            )

    def build_report(self, batch_id: str) -> dict:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT item_id, decision, status, labels, archived, draft_id,
                       actions_ok, actions_failed
                FROM batch_items
                WHERE batch_id = ?
                ORDER BY item_id
                """,
                (batch_id,),
            ).fetchall()
        if not rows and self.get_batch_exists(batch_id) is False:
            raise LookupError("Batch tidak ditemukan.")

        results = []
        approved = 0
        rejected = 0
        actions_ok = 0
        actions_failed = 0
        for row in rows:
            approved += row["decision"] == "approve"
            rejected += row["decision"] == "reject"
            actions_ok += row["actions_ok"]
            actions_failed += row["actions_failed"]
            if row["status"] in {"ok", "failed"}:
                item_status = row["status"]
            elif row["decision"] == "reject":
                item_status = "rejected"
            else:
                item_status = "skipped"
            results.append(
                {
                    "item_id": row["item_id"],
                    "status": item_status,
                    "applied": {
                        "labels": json.loads(row["labels"]),
                        "archived": bool(row["archived"]),
                        "draft_id": row["draft_id"],
                    },
                }
            )
        return {
            "summary": {
                "approved": approved,
                "rejected": rejected,
                "actions_ok": actions_ok,
                "actions_failed": actions_failed,
            },
            "results": results,
        }

    def get_batch_exists(self, batch_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        return row is not None

    def reconcile_on_start(self) -> int:
        placeholders = ", ".join("?" for _ in _IN_PROGRESS_STATUSES)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE batches
                SET status = 'failed', updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (_now(), *_IN_PROGRESS_STATUSES),
            )
        return cursor.rowcount
