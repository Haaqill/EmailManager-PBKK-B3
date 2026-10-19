"""MockGmailAPIClient — klien Gmail palsu dari eval/dataset.json (B).

Memenuhi protokol GmailClient (app/gmail/schemas.py), jadi tool dan graph
tidak membedakannya dari GmailAPIClient. Semua perubahan (label, arsip,
draft) hanya di memori dan hilang saat proses selesai.

Data dikembalikan MENTAH; redaksi dilakukan tool.
"""
from __future__ import annotations

import json
from email.utils import parseaddr
from pathlib import Path

from app.contracts import DatasetRow
from app.gmail.schemas import (
    GmailArchiveResult,
    GmailAttachment,
    GmailDraftResult,
    GmailLabelResult,
    GmailMessage,
    GmailThread,
    GmailThreadSummary,
)


def load_dataset(path: str | Path) -> list[DatasetRow]:
    """Baca dataset (array JSON, atau satu objek) dan validasi tiap baris."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        from app.config import PROJECT_DIR

        path = PROJECT_DIR / path   # path relatif di .env dihitung dari root proyek
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    return [DatasetRow.model_validate(r) for r in rows]


def _domain(address: str) -> str:
    return parseaddr(address)[1].rpartition("@")[2].lower()


class MockGmailAPIClient:
    """Klien Gmail palsu. Antarmukanya sama dengan GmailAPIClient."""

    def __init__(self, dataset_path: str | Path | None = None) -> None:
        if dataset_path is None:
            from app.config import get_config

            dataset_path = get_config().eval_dataset_path
        self.rows: dict[str, DatasetRow] = {r.id: r for r in load_dataset(dataset_path)}
        self.labels: dict[str, list[str]] = {tid: list(r.labels) for tid, r in self.rows.items()}
        self.unread: dict[str, bool] = {tid: r.unread for tid, r in self.rows.items()}
        self.drafts: list[dict] = []
        self.archived: list[str] = []
        self.labels_applied: list[dict] = []

    def _row(self, thread_id: str) -> DatasetRow:
        if thread_id not in self.rows:
            raise LookupError(f"thread {thread_id} tidak ada")
        return self.rows[thread_id]

    def list_threads(self, *, unread_only: bool, newer_than_days: int, in_inbox: bool,
                     sender_domain: str, max_results: int) -> list[GmailThreadSummary]:
        # newer_than_days diabaikan: tanggal dataset tetap.
        result = []
        for tid, row in self.rows.items():
            if unread_only and not self.unread[tid]:
                continue
            if in_inbox and "INBOX" not in self.labels[tid]:
                continue
            domain = _domain(row.messages[0].from_)
            if sender_domain and domain != sender_domain:
                continue
            last = row.messages[-1]
            result.append(GmailThreadSummary(
                thread_id=tid, subject=row.subject, from_domain=domain,
                snippet=last.body[:120], date=last.date,
                message_count=len(row.messages), has_attachments=bool(row.attachments),
            ))
            if len(result) >= max_results:
                break
        return result

    def get_thread(self, *, thread_id: str, max_messages: int) -> GmailThread:
        row = self._row(thread_id)
        return GmailThread(
            thread_id=thread_id,
            subject=row.subject,
            from_domain=_domain(row.messages[0].from_),
            messages=[GmailMessage(from_=m.from_, date=m.date, body_text=m.body)
                      for m in row.messages[-max_messages:]],
            attachments=[GmailAttachment(**a.model_dump()) for a in row.attachments],
        )

    def apply_labels(self, *, thread_id: str, category: str, priority: str,
                     reason: str) -> GmailLabelResult:
        self._row(thread_id)
        old = self.labels[thread_id]
        removed = [l for l in old if l.startswith(("Kategori/", "Prioritas/"))]
        applied = [f"Kategori/{category}", f"Prioritas/{priority}"]
        self.labels[thread_id] = [l for l in old if l not in removed] + applied
        self.labels_applied.append({"thread_id": thread_id, "applied": applied, "removed": removed})
        return GmailLabelResult(applied=applied, removed=removed)

    def archive(self, *, thread_id: str) -> GmailArchiveResult:
        self._row(thread_id)
        self.labels[thread_id] = [l for l in self.labels[thread_id] if l != "INBOX"]
        self.archived.append(thread_id)
        return GmailArchiveResult(archived=True)

    def create_draft(self, *, thread_id: str, body: str) -> GmailDraftResult:
        row = self._row(thread_id)
        draft_id = f"draft-{len(self.drafts) + 1}"
        self.drafts.append({"draft_id": draft_id, "thread_id": thread_id,
                            "to": row.messages[-1].from_, "subject": f"Re: {row.subject}",
                            "body": body})
        return GmailDraftResult(draft_id=draft_id)
