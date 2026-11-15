"""MockGmailAPIClient — klien Gmail palsu berbasis array eval/dataset.json."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
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
from pydantic import ValidationError

import json
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
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
from pydantic import ValidationError


def load_dataset(dataset_path: str | Path) -> list[DatasetRow]:
    """Baca array DatasetRow dari JSON dan validasi tiap baris.

    Dipakai MockGmailAPIClient dan DatasetLLM (LLM_BACKEND=mock).
    Path relatif yang tidak ada di cwd dihitung dari root proyek.
    """
    path = Path(dataset_path)
    if not path.is_absolute() and not path.exists():
        from app.config import PROJECT_DIR

        path = PROJECT_DIR / path
    try:
        with path.open(encoding="utf-8") as dataset_file:
            raw_rows = json.load(dataset_file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Dataset Gmail bukan JSON yang valid: {path}"
        ) from exc

    if not isinstance(raw_rows, list):
        raise ValueError(f"Dataset Gmail harus berupa array JSON: {path}")

    rows: list[DatasetRow] = []
    seen: set[str] = set()
    for index, raw_row in enumerate(raw_rows):
        try:
            row = DatasetRow.model_validate(raw_row)
        except ValidationError as exc:
            raise ValueError(
                f"Baris dataset Gmail ke-{index + 1} tidak valid."
            ) from exc
        if row.id in seen:
            raise ValueError(f"ID thread duplikat dalam dataset Gmail: {row.id}")
        seen.add(row.id)
        rows.append(row)
    return rows


class MockGmailAPIClient:
    """Klien Gmail palsu yang membaca array DatasetRow dari JSON."""

    def __init__(self, dataset_path: str | Path = "eval/dataset.json") -> None:
        self._threads: dict[str, DatasetRow] = {row.id: row for row in load_dataset(dataset_path)}
        self.drafts: list[dict[str, str]] = []

    def list_threads(
        self,
        *,
        unread_only: bool,
        newer_than_days: int,
        in_inbox: bool,
        sender_domain: str,
        max_results: int,
    ) -> list[GmailThreadSummary]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=newer_than_days)
        hasil: list[GmailThreadSummary] = []

        for row in self._threads.values():
            if unread_only and not row.unread:
                continue
            if in_inbox and "INBOX" not in row.labels:
                continue

            message_dates = [_parse_date(message.date) for message in row.messages]
            if not any(date >= cutoff for date in message_dates):
                continue
            if sender_domain and not any(
                _domain(message.from_) == sender_domain
                for message in row.messages
            ):
                continue

            first_message = row.messages[0]
            latest_message = row.messages[-1]
            snippet = " ".join(latest_message.body.split())[:200]
            hasil.append(
                GmailThreadSummary(
                    thread_id=row.id,
                    subject=row.subject,
                    from_domain=_domain(first_message.from_),
                    snippet=snippet,
                    date=max(message_dates).isoformat(),
                    message_count=len(row.messages),
                    has_attachments=bool(row.attachments),
                )
            )
            if len(hasil) >= max_results:
                break

        return hasil

    def get_thread(self, *, thread_id: str, max_messages: int) -> GmailThread:
        row = self._get_row(thread_id)
        first_message = row.messages[0]
        return GmailThread(
            thread_id=row.id,
            subject=row.subject,
            from_domain=_domain(first_message.from_),
            messages=[
                GmailMessage.model_validate(
                    {
                        "from": message.from_,
                        "date": message.date,
                        "body_text": message.body,
                    }
                )
                for message in row.messages[-max_messages:]
            ],
            attachments=[
                GmailAttachment(
                    name=attachment.name,
                    mime_type=attachment.mime_type,
                    size_bytes=attachment.size_bytes,
                )
                for attachment in row.attachments
            ],
        )

    def apply_labels(
        self,
        *,
        thread_id: str,
        category: str,
        priority: str,
        reason: str,
    ) -> GmailLabelResult:
        del reason
        row = self._get_row(thread_id)
        label_names = [f"Kategori/{category}", f"Prioritas/{priority}"]
        removed = [
            label
            for label in row.labels
            if label.startswith(("Kategori/", "Prioritas/"))
            and label not in label_names
        ]
        row.labels = [label for label in row.labels if label not in removed]
        row.labels.extend(label for label in label_names if label not in row.labels)
        return GmailLabelResult(applied=label_names, removed=removed)

    def archive(self, *, thread_id: str) -> GmailArchiveResult:
        row = self._get_row(thread_id)
        row.labels = [label for label in row.labels if label != "INBOX"]
        return GmailArchiveResult(archived=True)

    def create_draft(self, *, thread_id: str, body: str) -> GmailDraftResult:
        row = self._get_row(thread_id)
        owner = _first_address(row.messages[0].to)
        reply_to = next(
            (
                message
                for message in reversed(row.messages)
                if _first_address(message.from_) != owner
            ),
            None,
        )
        if reply_to is None:
            raise ValueError(f"Thread {thread_id!r} tidak memiliki pesan masuk untuk dibalas.")

        to_header = reply_to.from_
        subject = row.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        draft_id = f"draft-{len(self.drafts) + 1}"
        self.drafts.append(
            {
                "draft_id": draft_id,
                "thread_id": thread_id,
                "to": to_header,
                "subject": subject,
                "body": body,
            }
        )
        return GmailDraftResult(draft_id=draft_id)

    def _get_row(self, thread_id: str) -> DatasetRow:
        try:
            return self._threads[thread_id]
        except KeyError as exc:
            raise LookupError(f"Thread {thread_id!r} tidak ditemukan.") from exc


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_address(value: str) -> str:
    addresses = getaddresses([value])
    return addresses[0][1].lower() if addresses else ""


def _domain(value: str) -> str:
    address = _first_address(value)
    return address.rpartition("@")[2]
