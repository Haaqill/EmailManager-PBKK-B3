
"""Kontrak antarmuka Gmail Inbox Manager.

File ini adalah versi kode dari tab Kontrak.
Perubahan wajib direview pemilik kedua sisi kontrak.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Literal, Protocol, TypeVar
from pydantic import BaseModel, Field, field_validator, model_validator

# ─────────────────────────────────────────────────────────────
# 1. LLMClient (FINAL)
# ─────────────────────────────────────────────────────────────

class ToolCall(BaseModel):
    id: str          # dibuat client jika backend tidak memberi
    name: str
    arguments: dict  # sudah di-parse, TIDAK PERNAH string JSON

class Usage(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    model: str
    api_style: Literal["openai", "ollama"]
    tool_mode: Literal["native", "json"]
    retries: int

class LLMResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage

class LLMClient(Protocol):
    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse: ...

class LLMUnavailableError(Exception):
    """Server mati setelah retry."""

class LLMOutputError(Exception):
    """Output tetap rusak setelah 2 koreksi."""

# ─────────────────────────────────────────────────────────────
# 2. Tool & ToolResult (USULAN)
# ─────────────────────────────────────────────────────────────

class ErrorCode(str, Enum):
    VALIDATION = "validation"    # argumen tidak valid; LLM boleh koreksi (maks 2)
    NOT_FOUND = "not_found"      # thread_id tidak ada
    NOT_ALLOWED = "not_allowed"  # tool di luar allowlist / trash tanpa persetujuan
    INTERNAL = "internal"        # bug; dicatat, tidak dikoreksi LLM

T = TypeVar("T")

class ToolResult(BaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    error_code: ErrorCode | None = None
    message: str | None = None  # aman untuk LLM: tanpa stack trace/token/isi asli

    @model_validator(mode="after")
    def _cek_konsistensi(self) -> "ToolResult[T]":
        if self.ok and self.error_code is not None:
            raise ValueError("ToolResult.ok=True tidak boleh punya error_code")
        if not self.ok and self.error_code is None:
            raise ValueError("ToolResult.ok=False wajib punya error_code")
        return self

    @classmethod
    def sukses(cls, data: T) -> "ToolResult[T]":
        return cls(ok=True, data=data)

    @classmethod
    def gagal(cls, code: ErrorCode, message: str) -> "ToolResult[T]":
        return cls(ok=False, error_code=code, message=message)

@dataclass
class ToolContext:
    """Diisi dispatcher, tidak pernah oleh LLM."""
    batch_id: str
    pii_map: "PiiMap"
    allowed_tools: set[str]

# ─────────────────────────────────────────────────────────────
# 3. Redaksi PII (USULAN) — detail di app/privacy/redact.py
# ─────────────────────────────────────────────────────────────

class PiiMap(Protocol):
    """Satu per batch, hanya di memori.
    TIDAK PERNAH masuk log, state, disk, atau prompt."""
    ...

def redact(text: str, pii_map: PiiMap) -> str: ...
def restore(text: str, pii_map: PiiMap) -> str: ...
def html_to_text(html: str) -> str: ...

# ─────────────────────────────────────────────────────────────
# 4. Plan & Review (USULAN)
# ─────────────────────────────────────────────────────────────

Category = Literal["Akademik", "Tugas", "Pengumuman", "Pribadi", "Promosi", "Spam"]
Priority = Literal["Mendesak", "Normal", "Nanti"]
Action = Literal["keep", "archive", "trash"]  # trash: setelah MVP

class PlanItem(BaseModel):
    thread_id: str
    summary: str
    category: Category
    priority: Priority
    action: Action
    needs_reply: bool
    draft_body: str | None = None
    reason: str = Field(max_length=200)

    @field_validator("priority")
    @classmethod
    def promosi_spam_selalu_nanti(cls, v, info):
        cat = info.data.get("category")
        if cat in ("Promosi", "Spam") and v != "Nanti":
            raise ValueError("Promosi dan Spam selalu Nanti")
        return v

    @model_validator(mode="after")
    def _draft_konsisten_dengan_needs_reply(self) -> "PlanItem":
        if self.needs_reply and not self.draft_body:
            # draft_body diisi di node draft; saat PlanItem dirakit,
            # jika needs_reply=True maka draft_body wajib ada.
            raise ValueError("needs_reply=True wajib punya draft_body")
        return self

class ReviewDecision(BaseModel):
    thread_id: str
    status: Literal["approved", "edited", "rejected"]
    edited: PlanItem | None = None  # wajib jika status == "edited"

    @model_validator(mode="after")
    def _edited_wajib_jika_status_edited(self) -> "ReviewDecision":
        if self.status == "edited" and self.edited is None:
            raise ValueError("status='edited' wajib menyertakan field edited")
        if self.status != "edited" and self.edited is not None:
            raise ValueError("field edited hanya boleh diisi saat status='edited'")
        if self.edited is not None and self.edited.thread_id != self.thread_id:
            raise ValueError("edited.thread_id harus sama dengan thread_id")
        return self

class ActionRecord(BaseModel):
    thread_id: str
    tool: str
    ok: bool
    error_code: ErrorCode | None = None

# ─────────────────────────────────────────────────────────────
# 5. Dataset (USULAN) — satu baris JSONL per thread
# ─────────────────────────────────────────────────────────────

class DatasetMessage(BaseModel):
    """Satu pesan dalam thread. Field minimal yang dipakai tool & LLM."""

    from_: str = Field(alias="from")  # 'from' keyword Python
    to: str
    date: str  # ISO 8601
    body: str

    model_config = {"populate_by_name": True}

class DatasetAttachment(BaseModel):
    name: str
    mime_type: str
    size_bytes: int

class DatasetExpected(BaseModel):
    category: Category
    priority: Priority
    needs_reply: bool
    action: Action

class DatasetRow(BaseModel):
    id: str
    lang: Literal["id", "en"]
    unread: bool
    labels: list[str]
    subject: str
    messages: list[DatasetMessage]
    attachments: list[DatasetAttachment] = Field(default_factory=list)
    expected: DatasetExpected
    is_injection: bool = False
    notes: str = ""

    @field_validator("messages")
    @classmethod
    def _minimal_satu_pesan(cls, v: list[DatasetMessage]) -> list[DatasetMessage]:
        if not v:
            raise ValueError("thread minimal punya satu pesan")
        return v