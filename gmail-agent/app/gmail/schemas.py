"""Skema argumen dan hasil tool Gmail (kontrak 2).

File ini hanya berisi BENTUK DATA:
- Model argumen per tool (dipakai dispatcher untuk validasi Pydantic)
- Model hasil per tool (dipakai tool untuk mengembalikan data bertipe)
- Protokol GmailClient (antarmuka yang harus dipenuhi client asli & mock)

Tidak ada logika eksekusi di sini. Logika ada di tools.py.

Catatan dari kontrak:
- Tanpa X | None di argumen: Pydantic menulisnya anyOf, yang belum tentu
  ditangani model kampus. Pakai nilai default (string kosong, angka).
- max_results dibatasi 1..50, newer_than_days 1..90, max_messages 1..20.
- Domain pengirim dikirim terpisah lewat from_domain, bukan dari redact().
"""
from __future__ import annotations

from typing import Protocol
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import Category, Priority

_DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)

# thread_id Gmail hanya huruf, angka, _ dan -; menolak sisipan seperti "t001 OR x".
_THREAD_ID = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class _Args(BaseModel):
    """Basis argumen tool: argumen tak dikenal (mis. to_email) ditolak,
    sehingga dispatcher mengembalikan VALIDATION, bukan diam-diam diabaikan."""

    model_config = ConfigDict(extra="forbid")

# ══════════════════════════════════════════════════════════════════
# Protokol klien Gmail
# ══════════════════════════════════════════════════════════════════
# GmailAPIClient dan MockGmailAPIClient harus mengimplementasikan ini.
# Tool hanya memanggil method di protokol ini, tidak pernah Gmail API
# langsung. Dengan begitu, tool bisa diuji dengan mock.


class GmailThreadSummary(BaseModel):
    """Ringkasan satu thread dari scan_emails. SUDAH teredaksi."""

    thread_id: str
    subject: str            # sudah diredaksi
    from_domain: str        # domain pengirim, TIDAK diredaksi
    snippet: str            # sudah diredaksi
    date: str               # ISO 8601
    message_count: int
    has_attachments: bool


class GmailMessage(BaseModel):
    """Satu pesan dalam thread dari fetch_thread. SUDAH teredaksi."""

    from_: str = Field(alias="from")  # sudah diredaksi
    date: str
    body_text: str          # sudah diredaksi, HTML sudah jadi teks
    model_config = {"populate_by_name": True}


class GmailAttachment(BaseModel):
    """Metadata lampiran. Tidak mengunduh isinya."""

    name: str
    mime_type: str
    size_bytes: int


class GmailThread(BaseModel):
    """Isi lengkap satu thread dari fetch_thread. SUDAH teredaksi."""

    thread_id: str
    subject: str            # sudah diredaksi
    from_domain: str
    messages: list[GmailMessage]
    attachments: list[GmailAttachment]

    model_config = {"populate_by_name": True}


class GmailLabelResult(BaseModel):
    """Hasil label_thread."""

    applied: list[str]      # label yang dipasang
    removed: list[str]      # label lama yang dihapus


class GmailArchiveResult(BaseModel):
    """Hasil archive_thread."""

    archived: bool


class GmailDraftResult(BaseModel):
    """Hasil create_draft_reply."""

    draft_id: str


class GmailClient(Protocol):
    """Antarmuka klien Gmail. Diimplementasikan GmailAPIClient & Mock.

    Tool memanggil method ini dengan data MENTAH (belum diredaksi).
    Tanggung jawab redaksi ada di tool (lihat tools.py), karena tool
    yang memegang PiiMap lewat ToolContext.

    Method yang raise exception tidak diketahui akan dikonversi
    dispatcher menjadi ToolResult(INTERNAL).
    """

    def list_threads(
        self,
        *,
        unread_only: bool,
        newer_than_days: int,
        in_inbox: bool,
        sender_domain: str,
        max_results: int,
    ) -> list[GmailThreadSummary]:
        """Kembalikan thread MENTAH (belum diredaksi)."""
        ...

    def get_thread(
        self, *, thread_id: str, max_messages: int
    ) -> GmailThread:
        """Kembalikan isi thread MENTAH (belum diredaksi)."""
        ...

    def apply_labels(
        self,
        *,
        thread_id: str,
        category: str,
        priority: str,
        reason: str,
    ) -> GmailLabelResult:
        """Pasang label Kategori/<category> dan Prioritas/<priority>.
        Hapus label Kategori/* dan Prioritas/* lama dulu."""
        ...

    def archive(self, *, thread_id: str) -> GmailArchiveResult:
        """Hapus label INBOX."""
        ...

    def create_draft(
        self,
        *,
        thread_id: str,
        body: str,
    ) -> GmailDraftResult:
        """Buat draft balasan di thread yang sama."""
        ...


# ══════════════════════════════════════════════════════════════════
# Argumen tool (dipakai dispatcher untuk validasi Pydantic)
# ══════════════════════════════════════════════════════════════════


class ScanEmailsArgs(_Args):
    """Argumen scan_emails.

    Filter terstruktur: LLM TIDAK menulis query Gmail. Tool yang menyusun
    query, mis. is:unread newer_than:7d in:inbox.
    """

    unread_only: bool = True
    newer_than_days: int = Field(default=7, ge=1, le=90)
    in_inbox: bool = True
    sender_domain: str = ""  # default string kosong, BUKAN None
    max_results: int = Field(default=10, ge=1, le=50)

    @field_validator("sender_domain")
    @classmethod
    def _validasi_domain(cls, v: str) -> str:
        """Domain harus valid atau kosong. Mencegah injeksi query Gmail.

        Jika LLM mengirim domain tidak valid, dispatcher mengonversi
        error Pydantic ini menjadi ToolResult(VALIDATION), sehingga
        LLM bisa koreksi (maks 2).
        """
        if not v:
            return ""
        v = v.strip().lower()
        if not _DOMAIN_RE.match(v):
            raise ValueError(
                f"sender_domain tidak valid: {v!r}. "
                f"Contoh yang benar: 'univ.ac.id'"
            )
        return v

class FetchThreadArgs(_Args):
    thread_id: str = _THREAD_ID
    max_messages: int = Field(default=5, ge=1, le=20)


class LabelThreadArgs(_Args):
    thread_id: str = _THREAD_ID
    category: Category
    priority: Priority
    reason: str = Field(max_length=200)

    @field_validator("priority")
    @classmethod
    def _promosi_spam_selalu_nanti(cls, v, info):
        if info.data.get("category") in ("Promosi", "Spam") and v != "Nanti":
            raise ValueError("Promosi dan Spam selalu Nanti")
        return v


class ArchiveThreadArgs(_Args):
    thread_id: str = _THREAD_ID


class CreateDraftReplyArgs(_Args):
    thread_id: str = _THREAD_ID
    body: str = Field(min_length=1)


# ══════════════════════════════════════════════════════════════════
# Hasil tool (dikembalikan sebagai data ToolResult)
# ══════════════════════════════════════════════════════════════════


class ScanEmailsResult(BaseModel):
    threads: list[GmailThreadSummary]
    query: str  # query Gmail yang disusun tool, untuk debugging/log


class FetchThreadResult(BaseModel):
    thread: GmailThread


class LabelThreadResult(BaseModel):
    applied: list[str]
    removed: list[str]


class ArchiveThreadResult(BaseModel):
    archived: bool


class CreateDraftReplyResult(BaseModel):
    draft_id: str