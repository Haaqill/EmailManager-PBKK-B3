"""Kontrak Laravel <-> Python, tahap 1: bentuk `PlanSnapshot` yang dikirim ke Laravel.

Dokumen pendamping: docs/contract-laravel-python.md (root repo).
JSON Schema hasil ekspor: contracts/plan-schema.json (lihat export_plan_schema.py).

Berbeda dengan app/contracts.py (kontrak internal agen, teks TEREDAKSI), modul ini
mendefinisikan data yang KELUAR dari Python:
- teks sudah dipulihkan dengan `restore()`; LLM tidak pernah melihat data pribadi;
- `pii_map`, token Gmail, dan teks teredaksi tidak pernah masuk objek di sini;
- builder tidak menulis teks hasil `restore()` ke log atau stdout.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from email.utils import formataddr
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import Confidence, PiiMap
from app.gmail.schemas import GmailAttachment
from app.privacy.redact import PLACEHOLDER_RE, SECRET, parse_addresses, restore

Category = Literal["akademik", "tugas", "pengumuman", "pribadi", "promosi", "spam"]
Priority = Literal["mendesak", "normal", "nanti"]
Action = Literal["label_only", "archive", "draft_reply", "trash"]
WarningCode = Literal[
    "REPLY_TO_DOMAIN_MISMATCH",
    "NEW_RECIPIENT",
    "CROSS_THREAD_DATA",
    "UNRESOLVED_PLACEHOLDER",
]

# Alasan penambahan field; kalimatnya sama dengan tabel di docs/contract-laravel-python.md.
WHY_ITEM_ID = (
    "ID stabil per plan_version; dipakai Laravel untuk keputusan dan sebagai kunci "
    "idempotensi eksekusi."
)
WHY_THREAD = (
    "Laravel butuh subjek dan pengirim untuk menampilkan baris dan riwayat; di plan lama "
    "hanya ada thread_id, sedangkan Laravel tidak boleh memegang token Gmail untuk "
    "mencarinya sendiri."
)
WHY_CONFIDENCE = (
    "Keyakinan model terhadap kategori dan aksi (tinggi/sedang/rendah), untuk menyorot baris "
    "yang meragukan di UI. Tiga tingkat, bukan angka: skor angka dari LLM memberi presisi "
    "palsu, sedangkan tiga tingkat jujur soal ketidakpastian. Bukan gerbang keamanan: tidak "
    "mengubah keputusan bawaan, requires_confirmation, atau melewati review."
)
WHY_DRAFT_TO_SUBJECT = (
    "Prompt persetujuan Fase 2 menampilkan penerima sebenarnya; UI harus menampilkan hal "
    "yang sama karena pengguna menyetujui draft untuk penerima itu. Berasal dari header "
    "thread, bukan dari LLM."
)
WHY_WARNINGS = (
    "Peringatan wajib Fase 2 dibuat terstruktur supaya UI bisa menonjolkannya tanpa "
    "mengurai teks. Ditambah UNRESOLVED_PLACEHOLDER untuk placeholder yang gagal dipulihkan."
)
WHY_REQUIRES_CONFIRMATION = (
    "Trash berisiko tinggi dan wajib konfirmasi per item; ditentukan di Python agar tidak "
    "bergantung pada UI."
)
WHY_PLAN_VERSION = "Mencegah persetujuan dari tampilan yang sudah usang."
WHY_ALSO_ARCHIVE = (
    "Plan lama bisa berisi arsip dan draf sekaligus, sedangkan action hanya satu nilai; tanpa "
    "field ini niat arsip hilang dan pengguna tidak melihat seluruh aksi yang ia setujui. Hanya "
    "boleh true bila action == 'draft_reply'."
)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Attachment(_Out):
    """Metadata lampiran saja; isi lampiran tidak pernah dikirim."""

    filename: str
    type: str = Field(description="MIME type.")
    size: int = Field(ge=0, description="Ukuran dalam byte.")


class ThreadInfo(_Out):
    subject: str
    from_name: str
    from_domain: str
    date: str = Field(description="ISO 8601.")
    attachments: list[Attachment] = Field(default_factory=list)


class Draft(_Out):
    to: str = Field(description=WHY_DRAFT_TO_SUBJECT)
    subject: str = Field(description=WHY_DRAFT_TO_SUBJECT)
    body: str = Field(description="Isi draft setelah restore(); di plan lama bernama draft_body.")


class Warning(_Out):  # noqa: A001 - nama sesuai kontrak
    code: WarningCode
    message: str = Field(description="Teks untuk pengguna; tidak memuat isi placeholder.")


class PlanItem(_Out):
    """Satu item rencana untuk Laravel.

    Pemetaan dari `InboxState.plan` (app.contracts.PlanItem):
    - `InboxState.plan.draft_body` -> `draft.body`
    - `InboxState.plan.thread_id` tetap `thread_id`
    - `category`/`priority` diubah ke huruf kecil
    - `action`: keep -> label_only, archive -> archive, trash -> trash;
      item dengan draft (dan bukan trash) -> draft_reply
    - item archive + draft -> action draft_reply dengan also_archive = True
    """

    item_id: str = Field(pattern=r"^i_\d{2,}$", description=WHY_ITEM_ID)
    thread_id: str
    thread: ThreadInfo = Field(description=WHY_THREAD)
    category: Category
    priority: Priority
    action: Action
    also_archive: bool = Field(default=False, description=WHY_ALSO_ARCHIVE)
    reason: str
    confidence: Confidence | None = Field(default=None, description=WHY_CONFIDENCE)
    draft: Draft | None = Field(
        default=None, description="Wajib ada jika dan hanya jika action == 'draft_reply'."
    )
    warnings: list[Warning] = Field(default_factory=list, description=WHY_WARNINGS)
    requires_confirmation: bool = Field(description=WHY_REQUIRES_CONFIRMATION)

    @model_validator(mode="after")
    def _konsisten(self) -> "PlanItem":
        if (self.action == "draft_reply") != (self.draft is not None):
            raise ValueError("draft wajib ada jika dan hanya jika action == 'draft_reply'")
        if self.requires_confirmation != (self.action == "trash"):
            raise ValueError("requires_confirmation wajib True jika dan hanya jika action == 'trash'")
        if self.also_archive and self.action != "draft_reply":
            raise ValueError("also_archive hanya boleh True bila action == 'draft_reply'")
        return self


class PlanSnapshot(_Out):
    plan_version: int = Field(ge=1, description=WHY_PLAN_VERSION)
    items: list[PlanItem]


# --------------------------------------------------------------------------- #
# Masukan builder (tidak diserialisasi ke Laravel)
# --------------------------------------------------------------------------- #
class RawThreadMeta(BaseModel):
    """Metadata thread ASLI (sebelum redaksi), diambil pemanggil dari Gmail.

    `reply_to`: header penerima draft, ditentukan dengan aturan yang sama seperti
    GmailAPIClient.create_draft (Reply-To pesan yang dibalas, jika tidak ada From-nya).
    Kosong berarti memakai `from_`.
    """

    model_config = ConfigDict(populate_by_name=True)

    thread_id: str
    subject: str
    from_: str = Field(alias="from")
    date: str
    attachments: list[GmailAttachment] = Field(default_factory=list)
    reply_to: str = ""


_ACTION_MAP: dict[str, Action] = {"keep": "label_only", "archive": "archive", "trash": "trash"}


def _first_address(header: str) -> tuple[str, str]:
    parsed = parse_addresses(header)
    return parsed[0] if parsed else ("", "")


def _thread_info(meta: RawThreadMeta) -> ThreadInfo:
    name, address = _first_address(meta.from_)
    return ThreadInfo(
        subject=meta.subject,
        from_name=name or address,
        from_domain=address.rpartition("@")[2].lower() if "@" in address else "",
        date=meta.date,
        attachments=[
            Attachment(filename=a.name, type=a.mime_type, size=a.size_bytes)
            for a in meta.attachments
        ],
    )


def _reply_subject(subject: str) -> str:
    # Aturan sama dengan GmailAPIClient.create_draft.
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _reply_to(meta: RawThreadMeta) -> str:
    parsed = parse_addresses(meta.reply_to or meta.from_)
    return ", ".join(formataddr((name, addr)) for name, addr in parsed if addr)


def _unresolved_kinds(text: str) -> list[str]:
    return sorted({m.group("kind") for m in PLACEHOLDER_RE.finditer(text) if m.group(0) != SECRET})


def _unresolved_warning(field: str, kinds: Iterable[str]) -> Warning:
    return Warning(
        code="UNRESOLVED_PLACEHOLDER",
        message=f"Ada placeholder yang tidak dapat dipulihkan di {field} "
                f"(jenis: {', '.join(kinds)}). Periksa sebelum menyetujui.",
    )


def _restored(text: str, field: str, pii_map: PiiMap, warnings: list[Warning]) -> str:
    out = restore(text, pii_map)
    kinds = _unresolved_kinds(out)
    if kinds:
        warnings.append(_unresolved_warning(field, kinds))
    return out


def build_plan_snapshot(
    plan: list[dict[str, Any]],
    raw_threads: Mapping[str, RawThreadMeta],
    pii_map: PiiMap,
    plan_version: int,
) -> PlanSnapshot:
    """Rakit PlanSnapshot dari `InboxState.plan` (teredaksi) dan metadata thread asli.

    Fungsi murni: tidak memanggil Gmail/LLM, tidak menulis log, tidak mengubah masukan.
    `pii_map` hanya dipakai untuk restore() dan tidak disimpan di objek keluaran.
    KeyError jika thread_id di plan tidak ada di `raw_threads`.
    """
    items: list[PlanItem] = []
    for index, p in enumerate(plan, start=1):
        meta = raw_threads[p["thread_id"]]
        warnings: list[Warning] = []
        reason = _restored(p.get("reason") or "", "reason", pii_map, warnings)

        action = _ACTION_MAP[p["action"]]
        draft = None
        also_archive = False
        if p.get("draft_body") and action != "trash":
            also_archive = action == "archive"
            action = "draft_reply"
            draft = Draft(
                to=_reply_to(meta),
                subject=_reply_subject(meta.subject),
                body=_restored(p["draft_body"], "draft.body", pii_map, warnings),
            )
        # Peringatan Fase 2 lain (REPLY_TO_DOMAIN_MISMATCH, NEW_RECIPIENT, CROSS_THREAD_DATA)
        # belum punya logika di repo; kodenya sudah dicadangkan di WarningCode.

        items.append(PlanItem(
            item_id=f"i_{index:02d}",
            thread_id=p["thread_id"],
            thread=_thread_info(meta),
            category=p["category"].lower(),
            priority=p["priority"].lower(),
            action=action,
            also_archive=also_archive,
            reason=reason,
            confidence=p.get("confidence"),
            draft=draft,
            warnings=warnings,
            requires_confirmation=action == "trash",
        ))
    return PlanSnapshot(plan_version=plan_version, items=items)
