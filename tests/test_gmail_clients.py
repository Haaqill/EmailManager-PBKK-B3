from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError
from tenacity import wait_none

import app.gmail.client as gmail_client
from app.contracts import FatalToolError, ToolContext
from app.gmail.client import GmailAPIClient
from app.gmail.mock_client import MockGmailAPIClient
from app.gmail.schemas import FetchThreadArgs, ScanEmailsArgs
from app.gmail.tools import fetch_thread, scan_emails
from app.privacy.redact import pii_map_for, release_pii_map


def _http_error(status: int) -> HttpError:
    return HttpError(
        resp=SimpleNamespace(status=status, reason="test"),
        content=b"test error",
    )


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(
    sender: str,
    *,
    date: datetime,
    subject: str = "Pengumpulan Tugas",
    body: str = "Mohon periksa tugas.",
    mime_type: str = "text/plain",
    message_id: str = "<msg@example.test>",
    references: str = "",
) -> dict:
    headers = [
        {"name": "From", "value": sender},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": format_datetime(date)},
        {"name": "Message-ID", "value": message_id},
    ]
    if references:
        headers.append({"name": "References", "value": references})
    payload: dict = {
        "mimeType": mime_type,
        "headers": headers,
        "body": {"data": _encoded(body), "size": len(body)},
    }
    return {
        "id": "message-1",
        "internalDate": str(int(date.timestamp() * 1000)),
        "payload": payload,
    }


def _dataset_row(thread_id: str = "t001") -> dict:
    date = datetime.now(timezone.utc).isoformat()
    return {
        "id": thread_id,
        "lang": "id",
        "unread": True,
        "labels": ["INBOX", "Kategori/Tugas", "Prioritas/Mendesak"],
        "subject": "Contoh tugas",
        "messages": [
            {
                "from": "Dosen <dosen@univ.ac.id>",
                "to": "Mahasiswa <mahasiswa@example.com>",
                "date": date,
                "body": "Batas tugas hari Jumat.",
            }
        ],
        "attachments": [
            {
                "name": "rubrik.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 100,
            }
        ],
        "expected": {
            "category": "Tugas",
            "priority": "Mendesak",
            "needs_reply": False,
            "action": "keep",
        },
        "is_injection": False,
        "notes": "",
    }


class _Request:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result() if callable(self._result) else self._result


class _FakeService:
    def __init__(self, thread: dict):
        self.thread = thread
        self.calls: list[tuple[str, dict]] = []
        self.labels = [
            {"id": "INBOX", "name": "INBOX"},
            {"id": "old-category", "name": "Kategori/Lama"},
            {"id": "old-priority", "name": "Prioritas/Normal"},
            {"id": "other", "name": "Other"},
        ]
        self.draft_body: dict | None = None
        self.users_resource = _Users(self)

    def users(self):
        return self.users_resource


class _Users:
    def __init__(self, service: _FakeService):
        self.service = service

    def threads(self):
        return _Threads(self.service)

    def labels(self):
        return _Labels(self.service)

    def drafts(self):
        return _Drafts(self.service)

    def getProfile(self, **kwargs):
        self.service.calls.append(("getProfile", kwargs))
        return _Request({"emailAddress": "me@example.com"})


class _Threads:
    def __init__(self, service: _FakeService):
        self.service = service

    def list(self, **kwargs):
        self.service.calls.append(("threads.list", kwargs))
        return _Request(
            {"threads": [{"id": self.service.thread["id"]}]}
        )

    def get(self, **kwargs):
        self.service.calls.append(("threads.get", kwargs))
        return _Request(self.service.thread)

    def modify(self, **kwargs):
        self.service.calls.append(("threads.modify", kwargs))
        return _Request({})


class _Labels:
    def __init__(self, service: _FakeService):
        self.service = service

    def list(self, **kwargs):
        self.service.calls.append(("labels.list", kwargs))
        return _Request({"labels": self.service.labels})

    def create(self, **kwargs):
        self.service.calls.append(("labels.create", kwargs))
        label_id = f"created-{len(self.service.labels)}"
        self.service.labels.append(
            {"id": label_id, "name": kwargs["body"]["name"]}
        )
        return _Request({"id": label_id})


class _Drafts:
    def __init__(self, service: _FakeService):
        self.service = service

    def create(self, **kwargs):
        self.service.calls.append(("drafts.create", kwargs))
        self.service.draft_body = kwargs["body"]
        return _Request({"id": "draft-1"})


def _api_thread(messages: list[dict] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": "thread-1",
        "snippet": "Batas tugas hari Jumat.",
        "messages": messages
        or [_message("Dosen <dosen@univ.ac.id>", date=now)],
    }


def test_mock_client_loads_json_array_and_implements_protocol(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([_dataset_row()]), encoding="utf-8")

    client = MockGmailAPIClient(dataset)

    summaries = client.list_threads(
        unread_only=True,
        newer_than_days=7,
        in_inbox=True,
        sender_domain="univ.ac.id",
        max_results=10,
    )
    assert [summary.thread_id for summary in summaries] == ["t001"]
    assert summaries[0].from_domain == "univ.ac.id"
    assert summaries[0].has_attachments is True
    assert client.get_thread(thread_id="t001", max_messages=1).attachments[0].name == "rubrik.pdf"


def test_mock_client_filters_and_caps_results(tmp_path):
    first = _dataset_row("t001")
    second = _dataset_row("t002")
    second["unread"] = False
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([first, second]), encoding="utf-8")
    client = MockGmailAPIClient(dataset)

    results = client.list_threads(
        unread_only=True,
        newer_than_days=7,
        in_inbox=True,
        sender_domain="elsewhere.test",
        max_results=1,
    )
    assert results == []
    results = client.list_threads(
        unread_only=True,
        newer_than_days=7,
        in_inbox=True,
        sender_domain="",
        max_results=1,
    )
    assert len(results) == 1


def test_mock_client_mutates_labels_archive_and_draft(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([_dataset_row()]), encoding="utf-8")
    client = MockGmailAPIClient(dataset)

    labels = client.apply_labels(
        thread_id="t001",
        category="Akademik",
        priority="Normal",
        reason="Kelas",
    )
    assert labels.removed == ["Kategori/Tugas", "Prioritas/Mendesak"]
    assert labels.applied == ["Kategori/Akademik", "Prioritas/Normal"]
    same_labels = client.apply_labels(
        thread_id="t001",
        category="Akademik",
        priority="Normal",
        reason="Tidak berubah",
    )
    assert same_labels.removed == []
    assert client.archive(thread_id="t001").archived is True

    draft = client.create_draft(thread_id="t001", body="Terima kasih.")
    assert draft.draft_id == "draft-1"
    assert client.drafts[0]["to"] == "Dosen <dosen@univ.ac.id>"
    assert client.drafts[0]["subject"] == "Re: Contoh tugas"
    assert client.drafts[0]["thread_id"] == "t001"


def test_mock_client_rejects_non_array_and_duplicate_ids(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps(_dataset_row()), encoding="utf-8")
    with pytest.raises(ValueError, match="array JSON"):
        MockGmailAPIClient(dataset)

    dataset.write_text(
        json.dumps([_dataset_row("same"), _dataset_row("same")]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplikat"):
        MockGmailAPIClient(dataset)


def test_mock_client_raises_lookup_error_for_missing_thread(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([_dataset_row()]), encoding="utf-8")
    client = MockGmailAPIClient(dataset)

    with pytest.raises(LookupError):
        client.get_thread(thread_id="missing", max_messages=5)


def test_gmail_tools_use_dataset_mock_and_redact_pii(tmp_path):
    row = _dataset_row()
    row["subject"] = "Pertanyaan dari sari.w@univ.ac.id"
    row["messages"][0]["from"] = (
        "Dr. Sari Wulandari <sari.w@univ.ac.id>"
    )
    row["messages"][0]["body"] = (
        "Silakan hubungi sari.w@univ.ac.id untuk informasi tugas."
    )
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([row]), encoding="utf-8")
    client = MockGmailAPIClient(dataset)
    pii_map = pii_map_for("gmail-mock-integration")
    context = ToolContext(
        batch_id="gmail-mock-integration",
        pii_map=pii_map,
        allowed_tools={"scan_emails", "fetch_thread"},
        gmail_client=client,
    )

    try:
        scanned = scan_emails(ScanEmailsArgs(newer_than_days=90), context)
        fetched = fetch_thread(FetchThreadArgs(thread_id="t001"), context)
        combined = repr(scanned.data) + repr(fetched.data)
        assert scanned.ok and fetched.ok
        assert "sari.w@univ.ac.id" not in combined
        assert "Sari Wulandari" not in combined
        assert "<EMAIL_1>" in combined
    finally:
        release_pii_map("gmail-mock-integration")


def test_api_client_builds_query_and_extracts_thread_summary():
    service = _FakeService(_api_thread())
    client = GmailAPIClient(service=service)

    results = client.list_threads(
        unread_only=True,
        newer_than_days=3,
        in_inbox=True,
        sender_domain="univ.ac.id",
        max_results=4,
    )

    assert results[0].thread_id == "thread-1"
    assert results[0].from_domain == "univ.ac.id"
    assert results[0].date.endswith("+00:00")
    assert service.calls[0] == (
        "threads.list",
        {
            "userId": "me",
            "q": "is:unread newer_than:3d in:inbox from:@univ.ac.id",
            "maxResults": 4,
        },
    )


def test_api_client_extracts_plain_html_and_attachment_metadata():
    now = datetime.now(timezone.utc)
    html_part = {
        "mimeType": "text/html",
        "body": {"data": _encoded("<p>Isi <b>HTML</b></p>")},
    }
    attachment_part = {
        "mimeType": "application/pdf",
        "filename": "rubrik.pdf",
        "body": {"attachmentId": "attachment-1", "size": 123},
    }
    message = _message("Dosen <dosen@univ.ac.id>", date=now)
    message["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": message["payload"]["headers"],
        "parts": [html_part, attachment_part],
    }
    client = GmailAPIClient(service=_FakeService(_api_thread([message])))

    thread = client.get_thread(thread_id="thread-1", max_messages=5)

    assert thread.messages[0].body_text == "Isi HTML"
    assert thread.attachments[0].name == "rubrik.pdf"
    assert thread.attachments[0].size_bytes == 123


def test_api_client_replaces_labels_archives_and_creates_reply_draft():
    now = datetime.now(timezone.utc)
    incoming = _message(
        "Dosen <dosen@univ.ac.id>",
        date=now - timedelta(minutes=5),
        message_id="<first@example.test>",
        references="<older@example.test>",
    )
    own = _message(
        "Me <me@example.com>",
        date=now - timedelta(minutes=2),
        message_id="<own@example.test>",
    )
    latest_incoming = _message(
        "Koordinator <coord@univ.ac.id>",
        date=now,
        message_id="<latest@example.test>",
        references="<older@example.test> <first@example.test>",
    )
    service = _FakeService(_api_thread([incoming, own, latest_incoming]))
    client = GmailAPIClient(service=service)

    label_result = client.apply_labels(
        thread_id="thread-1",
        category="Tugas",
        priority="Mendesak",
        reason="Deadline dekat",
    )
    assert label_result.removed == ["Kategori/Lama", "Prioritas/Normal"]
    assert "Kategori/Tugas" in label_result.applied
    assert client.archive(thread_id="thread-1").archived is True
    draft = client.create_draft(thread_id="thread-1", body="Siap, terima kasih.")

    assert draft.draft_id == "draft-1"
    assert service.draft_body is not None
    draft_message = service.draft_body["message"]
    assert draft_message["threadId"] == "thread-1"
    raw = draft_message["raw"]
    raw += "=" * (-len(raw) % 4)
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw))
    assert parsed["To"] == "Koordinator <coord@univ.ac.id>"
    assert parsed["Subject"] == "Re: Pengumpulan Tugas"
    assert parsed["In-Reply-To"] == "<latest@example.test>"
    assert parsed["References"] == (
        "<older@example.test> <first@example.test> <latest@example.test>"
    )
    payload = parsed.get_payload(decode=True)
    assert isinstance(payload, bytes)
    assert payload.decode().strip() == "Siap, terima kasih."


def test_api_client_maps_404_to_lookup_error():
    service = _FakeService(_api_thread())
    client = GmailAPIClient(service=service)
    request = _Request(_http_error(404))

    with pytest.raises(LookupError):
        client._execute(request)


def test_api_client_loads_credentials_and_builds_gmail_service(monkeypatch):
    calls = []
    credentials = object()
    service = _FakeService(_api_thread())

    monkeypatch.setattr(gmail_client, "get_credentials", lambda: credentials)
    monkeypatch.setattr(
        gmail_client,
        "build",
        lambda *args, **kwargs: calls.append((args, kwargs)) or service,
    )

    client = GmailAPIClient(config=object())

    assert client._service is service
    assert calls == [
        (
            ("gmail", "v1"),
            {"credentials": credentials, "cache_discovery": False},
        )
    ]


def test_api_client_turns_reauth_requirement_into_fatal_error(monkeypatch):
    monkeypatch.setattr(
        gmail_client,
        "get_credentials",
        lambda: (_ for _ in ()).throw(
            gmail_client.ReauthRequired("login ulang diperlukan")
        ),
    )

    with pytest.raises(FatalToolError, match="login ulang"):
        GmailAPIClient()


def test_api_client_retries_transient_errors_and_fails_fatally(monkeypatch):
    monkeypatch.setattr(gmail_client._execute_with_retry.retry, "wait", wait_none())
    service = _FakeService(_api_thread())
    client = GmailAPIClient(service=service)

    attempts = {"count": 0}

    def succeeds_on_third_attempt():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _http_error(503)
        return {"ok": True}

    assert client._execute(_Request(succeeds_on_third_attempt)) == {"ok": True}
    assert attempts["count"] == 3

    attempts["count"] = 0

    def always_fails():
        attempts["count"] += 1
        raise _http_error(429)

    with pytest.raises(FatalToolError, match="3 percobaan"):
        client._execute(_Request(always_fails))
    assert attempts["count"] == 3
