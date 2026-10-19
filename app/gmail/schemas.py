"""Skema argumen dan hasil tool Gmail (kontrak 2, B).

Aturan skema argumen (dibaca LLM):
- extra="forbid": argumen tak dikenal (mis. to_email) menjadi VALIDATION.
- Tanpa `X | None`: Pydantic menulisnya sebagai anyOf, yang belum tentu
  ditangani model kampus. Pakai nilai default.
- LLM tidak menulis query Gmail; scan_emails menerima filter terstruktur.
- create_draft_reply hanya thread_id + body; penerima dan subjek diambil
  tool dari header thread, supaya isi email tidak bisa mengalihkan penerima.

Tidak ada tool untuk mengirim email atau menghapus permanen.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import Category, Priority

_THREAD_ID = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
# Domain polos (mis. univ.ac.id) atau kosong. Mencegah operator query
# seperti "x.com OR in:trash" masuk ke query Gmail.
_DOMAIN_PATTERN = r"^$|^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------- argumen tool

class ScanEmailsArgs(_Args):
    unread_only: bool = True
    newer_than_days: int = Field(default=7, ge=1, le=90)
    in_inbox: bool = True
    sender_domain: str = Field(default="", max_length=253, pattern=_DOMAIN_PATTERN)
    max_results: int = Field(default=10, ge=1, le=50)


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
    def promosi_spam_selalu_nanti(cls, v, info):
        if info.data.get("category") in ("Promosi", "Spam") and v != "Nanti":
            raise ValueError("Promosi dan Spam selalu Nanti")
        return v


class ArchiveThreadArgs(_Args):
    thread_id: str = _THREAD_ID


class CreateDraftReplyArgs(_Args):
    thread_id: str = _THREAD_ID
    body: str = Field(min_length=1)


class TrashThreadArgs(_Args):
    """Setelah MVP. Dispatcher hanya mengeksekusi jika ada ReviewDecision approved."""
    thread_id: str = _THREAD_ID


# ---------------------------------------------------------- isi ToolResult.data

class ThreadSummary(BaseModel):
    thread_id: str
    subject: str
    from_domain: str
    snippet: str
    date: str
    message_count: int
    has_attachments: bool


class ScanEmailsResult(BaseModel):
    threads: list[ThreadSummary]


class MessageView(BaseModel):
    from_: str = Field(alias="from")  # 'from' keyword Python
    date: str
    body_text: str

    model_config = {"populate_by_name": True}


class AttachmentMeta(BaseModel):
    name: str
    mime_type: str
    size_bytes: int


class FetchThreadResult(BaseModel):
    subject: str
    messages: list[MessageView]
    attachments: list[AttachmentMeta] = Field(default_factory=list)


class LabelThreadResult(BaseModel):
    applied: list[str]
    removed: list[str]


class ArchiveThreadResult(BaseModel):
    archived: bool


class CreateDraftReplyResult(BaseModel):
    draft_id: str


class TrashThreadResult(BaseModel):
    trashed: bool


# ---------------------------------------------------------- registry

TOOL_ARGS: dict[str, type[BaseModel]] = {
    "scan_emails": ScanEmailsArgs,
    "fetch_thread": FetchThreadArgs,
    "label_thread": LabelThreadArgs,
    "archive_thread": ArchiveThreadArgs,
    "create_draft_reply": CreateDraftReplyArgs,
    "trash_thread": TrashThreadArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "scan_emails": "Cari thread email dengan filter terstruktur; mengembalikan metadata dan snippet teredaksi.",
    "fetch_thread": "Ambil isi teks teredaksi sebuah thread (pesan terakhir) dan metadata lampiran.",
    "label_thread": "Pasang satu label kategori dan satu label prioritas pada thread; label lama diganti.",
    "archive_thread": "Arsipkan thread (hapus dari INBOX). Tidak menghapus email.",
    "create_draft_reply": "Buat draft balasan (tidak dikirim). Penerima dan subjek diambil dari thread.",
    "trash_thread": "Pindahkan thread ke Sampah. Hanya dengan persetujuan pengguna per item.",
}

MVP_TOOLS: frozenset[str] = frozenset(
    {"scan_emails", "fetch_thread", "label_thread", "archive_thread", "create_draft_reply"}
)


def openai_tool_schemas(names: frozenset[str] | set[str] = MVP_TOOLS) -> list[dict[str, Any]]:
    """Skema tool format OpenAI Chat Completions, urut sesuai TOOL_ARGS."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": model.model_json_schema(),
            },
        }
        for name, model in TOOL_ARGS.items()
        if name in names
    ]
