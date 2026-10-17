
"""Kontrak antarmuka Gmail Inbox Manager.

File ini adalah versi kode dari tab Kontrak.
Perubahan wajib direview pemilik kedua sisi kontrak.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Literal, Protocol, TypeVar
from pydantic import BaseModel, Field, field_validator

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

class ReviewDecision(BaseModel):
    thread_id: str
    status: Literal["approved", "edited", "rejected"]
    edited: PlanItem | None = None  # wajib jika status == "edited"

class ActionRecord(BaseModel):
    thread_id: str
    tool: str
    ok: bool
    error_code: ErrorCode | None = None

# ─────────────────────────────────────────────────────────────
# 5. Dataset (USULAN) — satu baris JSONL per thread
# ─────────────────────────────────────────────────────────────

class DatasetRow(BaseModel):
    id: str
    lang: Literal["id", "en"]
    unread: bool
    labels: list[str]
    subject: str
    messages: list[dict]
    attachments: list[dict] = []
    expected: dict
    is_injection: bool = False
    notes: str = ""
    