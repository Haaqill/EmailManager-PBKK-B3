"""GmailAPIClient — klien Gmail asli (M1, B)."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import getaddresses
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from app.contracts import FatalToolError
from app.gmail.auth import ReauthRequired, get_credentials
from app.gmail.schemas import (
    GmailArchiveResult,
    GmailAttachment,
    GmailDraftResult,
    GmailLabelResult,
    GmailMessage,
    GmailThread,
    GmailThreadSummary,
)
from app.gmail.query import build_gmail_query
from app.privacy.redact import html_to_text

_CATEGORY_PREFIXES = ("Kategori/", "Prioritas/")


class GmailAPIClient:
    """Implementasi GmailClient yang memakai kredensial OAuth dari keyring."""

    def __init__(
        self, config: Any | None = None, *, service: Any | None = None
    ) -> None:
        del config
        if service is not None:
            self._service = service
            return

        try:
            credentials = get_credentials()
        except ReauthRequired as exc:
            raise FatalToolError(str(exc)) from exc
        self._service = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        )

    def list_threads(
        self,
        *,
        unread_only: bool,
        newer_than_days: int,
        in_inbox: bool,
        sender_domain: str,
        max_results: int,
    ) -> list[GmailThreadSummary]:
        query = build_gmail_query(
            unread_only=unread_only,
            newer_than_days=newer_than_days,
            in_inbox=in_inbox,
            sender_domain=sender_domain,
        )
        response = self._execute(
            self._service.users()
            .threads()
            .list(userId="me", q=query, maxResults=max_results)
        )

        summaries: list[GmailThreadSummary] = []
        for thread_ref in response.get("threads", []):
            thread_id = thread_ref.get("id")
            if not thread_id:
                raise ValueError("Gmail mengembalikan thread tanpa ID.")
            thread = self._execute(
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
            )
            messages = thread.get("messages", [])
            if not messages:
                raise ValueError(f"Thread Gmail {thread_id!r} tidak memiliki pesan.")
            first_payload = messages[0].get("payload", {})
            latest = messages[-1]
            summaries.append(
                GmailThreadSummary(
                    thread_id=thread_id,
                    subject=_header(first_payload, "Subject"),
                    from_domain=_email_domain(_header(first_payload, "From")),
                    snippet=thread.get("snippet", ""),
                    date=_message_date(latest),
                    message_count=len(messages),
                    has_attachments=bool(_attachments(messages)),
                )
            )
        return summaries

    def get_thread(self, *, thread_id: str, max_messages: int) -> GmailThread:
        thread = self._execute(
            self._service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
        )
        messages = thread.get("messages", [])
        if not messages:
            raise LookupError(f"Thread {thread_id!r} tidak ditemukan.")

        first_payload = messages[0].get("payload", {})
        return GmailThread(
            thread_id=thread_id,
            subject=_header(first_payload, "Subject"),
            from_domain=_email_domain(_header(first_payload, "From")),
            messages=[
                GmailMessage.model_validate(
                    {
                        "from": _header(message.get("payload", {}), "From"),
                        "date": _message_date(message),
                        "body_text": _message_body(message.get("payload", {})),
                    }
                )
                for message in messages[-max_messages:]
            ],
            attachments=[
                attachment
                for message in messages
                for attachment in _attachments([message])
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
        self._execute(
            self._service.users()
            .threads()
            .get(userId="me", id=thread_id, format="metadata")
        )

        labels_response = self._execute(
            self._service.users().labels().list(userId="me")
        )
        labels = {
            label["name"]: label["id"]
            for label in labels_response.get("labels", [])
            if label.get("name") and label.get("id")
        }
        desired_labels = [f"Kategori/{category}", f"Prioritas/{priority}"]
        old_labels = [
            name
            for name in labels
            if name.startswith(_CATEGORY_PREFIXES) and name not in desired_labels
        ]

        for name in desired_labels:
            if name not in labels:
                created = self._execute(
                    self._service.users()
                    .labels()
                    .create(userId="me", body={"name": name})
                )
                label_id = created.get("id")
                if not label_id:
                    raise ValueError(f"Gmail tidak mengembalikan ID label {name!r}.")
                labels[name] = label_id

        self._execute(
            self._service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={
                    "addLabelIds": [labels[name] for name in desired_labels],
                    "removeLabelIds": [labels[name] for name in old_labels],
                },
            )
        )
        return GmailLabelResult(applied=desired_labels, removed=old_labels)

    def archive(self, *, thread_id: str) -> GmailArchiveResult:
        self._execute(
            self._service.users()
            .threads()
            .modify(
                userId="me",
                id=thread_id,
                body={"removeLabelIds": ["INBOX"]},
            )
        )
        return GmailArchiveResult(archived=True)

    def create_draft(self, *, thread_id: str, body: str) -> GmailDraftResult:
        thread = self._execute(
            self._service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
        )
        messages = thread.get("messages", [])
        if not messages:
            raise LookupError(f"Thread {thread_id!r} tidak ditemukan.")

        profile = self._execute(
            self._service.users().getProfile(userId="me")
        )
        own_email = profile.get("emailAddress", "").lower()
        if not own_email:
            raise ValueError("Gmail tidak mengembalikan alamat akun yang aktif.")

        reply_target = next(
            (
                message
                for message in reversed(messages)
                if _email_address(_header(message.get("payload", {}), "From"))
                != own_email
            ),
            None,
        )
        if reply_target is None:
            raise ValueError(f"Thread {thread_id!r} tidak memiliki pesan masuk untuk dibalas.")

        target_payload = reply_target.get("payload", {})
        target_headers = _headers(target_payload)
        to_value = target_headers.get("reply-to") or target_headers.get("from")
        if not to_value:
            raise ValueError(f"Pesan pada thread {thread_id!r} tidak memiliki pengirim.")

        subject = (
            target_headers.get("subject")
            or _header(messages[0].get("payload", {}), "Subject")
        )
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        email = EmailMessage()
        email["To"] = _decode_header(to_value)
        email["Subject"] = subject
        message_id = target_headers.get("message-id")
        if message_id:
            email["In-Reply-To"] = message_id
        references = target_headers.get("references", "").strip()
        if message_id and message_id not in references.split():
            references = f"{references} {message_id}".strip()
        if references:
            email["References"] = references
        email.set_content(body)

        raw = base64.urlsafe_b64encode(email.as_bytes()).decode("ascii").rstrip("=")
        draft = self._execute(
            self._service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"threadId": thread_id, "raw": raw}},
            )
        )
        draft_id = draft.get("id")
        if not draft_id:
            raise ValueError("Gmail tidak mengembalikan ID draft.")
        return GmailDraftResult(draft_id=draft_id)

    def _execute(self, request: Any) -> dict[str, Any]:
        try:
            return _execute_with_retry(request)
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 404:
                raise LookupError("Thread atau resource Gmail tidak ditemukan.") from exc
            if _is_retryable(exc):
                raise FatalToolError(
                    f"Gmail API gagal setelah 3 percobaan (HTTP {status})."
                ) from exc
            raise


def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, HttpError):
        return False
    status = getattr(exc.resp, "status", 0)
    return status == 429 or 500 <= status < 600


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_random_exponential(multiplier=0.5, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _execute_with_retry(request: Any) -> dict[str, Any]:
    return request.execute()


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        header.get("name", "").lower(): _decode_header(header.get("value", ""))
        for header in payload.get("headers", [])
        if header.get("name")
    }


def _header(payload: dict[str, Any], name: str) -> str:
    return _headers(payload).get(name.lower(), "")


def _decode_header(value: str) -> str:
    return str(make_header(decode_header(value)))


def _email_address(value: str) -> str:
    addresses = getaddresses([value])
    return addresses[0][1].lower() if addresses else ""


def _email_domain(value: str) -> str:
    return _email_address(value).rpartition("@")[2]


def _message_date(message: dict[str, Any]) -> str:
    internal_date = message.get("internalDate")
    if internal_date is not None:
        return datetime.fromtimestamp(
            int(internal_date) / 1000, tz=timezone.utc
        ).isoformat()
    date_header = _header(message.get("payload", {}), "Date")
    if not date_header:
        raise ValueError("Pesan Gmail tidak memiliki tanggal.")
    from email.utils import parsedate_to_datetime

    parsed = parsedate_to_datetime(date_header)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _message_body(payload: dict[str, Any]) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def collect(part: dict[str, Any]) -> None:
        if part.get("filename"):
            return
        mime_type = part.get("mimeType", "").lower()
        data = part.get("body", {}).get("data")
        if data and mime_type in {"text/plain", "text/html"}:
            decoded = _decode_body(data, part)
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            else:
                html_parts.append(decoded)
        for child in part.get("parts", []):
            collect(child)

    collect(payload)
    if plain_parts:
        return "\n".join(plain_parts).strip()
    return html_to_text("\n".join(html_parts))


def _decode_body(data: str, part: dict[str, Any]) -> str:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded)
    content_type = Message()
    for header in part.get("headers", []):
        if header.get("name", "").lower() == "content-type":
            content_type["content-type"] = header.get("value", "")
            break
    charset = content_type.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _attachments(messages: list[dict[str, Any]]) -> list[GmailAttachment]:
    found: list[GmailAttachment] = []

    def collect(part: dict[str, Any]) -> None:
        filename = part.get("filename", "")
        if filename:
            found.append(
                GmailAttachment(
                    name=filename,
                    mime_type=part.get("mimeType", "application/octet-stream"),
                    size_bytes=part.get("body", {}).get("size", 0),
                )
            )
        for child in part.get("parts", []):
            collect(child)

    for message in messages:
        collect(message.get("payload", {}))
    return found
