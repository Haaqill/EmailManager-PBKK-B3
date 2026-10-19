"""Implementasi 5 tool MVP (B).

Setiap tool:
- Menerima args (BaseModel) + ctx (ToolContext)
- Memanggil ctx.gmail_client (GmailAPIClient atau MockGmailAPIClient)
- Untuk scan_emails & fetch_thread: Meredaksi data SEBELUM return
- Mengembalikan ToolResult

Registrasi ke dispatcher dilakukan di fungsi register_all_tools(),
dipanggil sekali saat aplikasi start (atau di fixture tes).

Aturan dari kontrak:
- Filter terstruktur: LLM tidak menulis query Gmail.
- label_thread: hapus label Kategori/* dan Prioritas/* lama, lalu pasang baru.
- create_draft_reply: penerima & subjek dari header thread (bukan argumen).
- trash_thread: SETELAH MVP.
"""
from __future__ import annotations

from typing import Any

from app.contracts import (
    FatalToolError,
    NotFoundError,
    ToolContext,
    ToolResult,
)
from app.gmail.schemas import (
    ArchiveThreadArgs,
    ArchiveThreadResult,
    CreateDraftReplyArgs,
    CreateDraftReplyResult,
    FetchThreadArgs,
    FetchThreadResult,
    GmailClient,
    LabelThreadArgs,
    LabelThreadResult,
    ScanEmailsArgs,
    ScanEmailsResult,
)


# ══════════════════════════════════════════════════════════════════
# Helper
# ══════════════════════════════════════════════════════════════════


def _client(ctx: ToolContext) -> GmailClient:
    """Ambil GmailClient dari ctx. Raise fatal jika tidak ada.

    Dispatcher menyediakan client lewat ToolContext. Jika tidak ada,
    itu bug programmer, bukan kesalahan LLM. Raise FatalToolError agar
    batch berhenti, bukan diam-diam mengembalikan ToolResult(INTERNAL).
    """
    client = getattr(ctx, "gmail_client", None)
    if client is None:
        raise FatalToolError(
            "ToolContext tidak menyediakan gmail_client. "
            "Dispatcher harus mengisi field ini sebelum memanggil tool."
        )
    return client


def _redact(text: str, ctx: ToolContext) -> str:
    """Redaksi satu string. Panggil redact() dari C."""
    if not text:
        return text
    from app.privacy.redact import redact

    return redact(text, ctx.pii_map)


def _redact_domain(domain: str) -> str:
    """Domain TIDAK diredaksi. Hanya normalisasi.

    Domain pengirim tetap terlihat lewat from_domain (kontrak 3),
    supaya workflow bisa membedakan kampus vs vendor tanpa
    membuka alamat lengkap.
    """
    return (domain or "").strip().lower()


def _bangun_query(args: ScanEmailsArgs) -> str:
    """Susun query Gmail dari filter terstruktur.

    LLM tidak menulis query. Tool yang menyusun, agar tidak ada
    injeksi query dari LLM.

    sender_domain sudah divalidasi Pydantic di ScanEmailsArgs,
    jadi aman dipakai langsung.
    """
    bagian = []
    if args.unread_only:
        bagian.append("is:unread")
    bagian.append(f"newer_than:{args.newer_than_days}d")
    if args.in_inbox:
        bagian.append("in:inbox")
    if args.sender_domain:
        bagian.append(f"from:@{args.sender_domain}")
    return " ".join(bagian)

# ══════════════════════════════════════════════════════════════════
# Tool 1: scan_emails
# ══════════════════════════════════════════════════════════════════


def scan_emails(
    args: ScanEmailsArgs, ctx: ToolContext
) -> ToolResult[ScanEmailsResult]:
    """Daftar thread sesuai filter. Data SUDAH diredaksi saat return.

    Redaksi:
    - subject   → redact()
    - snippet   → redact()
    - from_domain → TIDAK diredaksi
    """
    client = _client(ctx)
    mentah = client.list_threads(
        unread_only=args.unread_only,
        newer_than_days=args.newer_than_days,
        in_inbox=args.in_inbox,
        sender_domain=args.sender_domain,
        max_results=args.max_results,
    )

    # Redaksi setiap thread SEBELUM masuk ToolResult
    teredaksi = []
    for t in mentah:
        teredaksi.append(
            t.model_copy(
                update={
                    "subject": _redact(t.subject, ctx),
                    "snippet": _redact(t.snippet, ctx),
                    "from_domain": _redact_domain(t.from_domain),
                }
            )
        )

    return ToolResult.sukses(
        ScanEmailsResult(threads=teredaksi, query=_bangun_query(args))
    )


# ══════════════════════════════════════════════════════════════════
# Tool 2: fetch_thread
# ══════════════════════════════════════════════════════════════════


def fetch_thread(
    args: FetchThreadArgs, ctx: ToolContext
) -> ToolResult[FetchThreadResult]:
    """Ambil isi thread. Data SUDAH diredaksi saat return.

    Redaksi:
    - subject   → redact()
    - from_     → redact() (header From termasuk nama & email)
    - body_text → redact()
    - attachments (name, mime_type, size) → TIDAK diredaksi di MVP
      (nama file lampiran diredaksi SETELAH MVP)
    """
    client = _client(ctx)

    try:
        mentah = client.get_thread(
            thread_id=args.thread_id, max_messages=args.max_messages
        )
    except LookupError as exc:
        # Klien raise LookupError jika thread tidak ada
        raise NotFoundError(f"Thread {args.thread_id!r} tidak ditemukan.") from exc

    # Redaksi setiap pesan
    pesan_teredaksi = [
        m.model_copy(
            update={
                "from_": _redact(m.from_, ctx),
                "body_text": _redact(m.body_text, ctx),
            }
        )
        for m in mentah.messages
    ]

    thread_teredaksi = mentah.model_copy(
        update={
            "subject": _redact(mentah.subject, ctx),
            "from_domain": _redact_domain(mentah.from_domain),
            "messages": pesan_teredaksi,
        }
    )

    return ToolResult.sukses(FetchThreadResult(thread=thread_teredaksi))


# ══════════════════════════════════════════════════════════════════
# Tool 3: label_thread
# ══════════════════════════════════════════════════════════════════


def label_thread(
    args: LabelThreadArgs, ctx: ToolContext
) -> ToolResult[LabelThreadResult]:
    """Pasang label Kategori/<cat> dan Prioritas/<pri>.

    Klien bertanggung jawab menghapus label Kategori/* dan Prioritas/*
    lama sebelum memasang yang baru (kontrak 2, poin 3).
    """
    client = _client(ctx)
    try:
        hasil = client.apply_labels(
            thread_id=args.thread_id,
            category=args.category,
            priority=args.priority,
            reason=args.reason,
        )
    except LookupError as exc:
        raise NotFoundError(f"Thread {args.thread_id!r} tidak ditemukan.") from exc

    return ToolResult.sukses(
        LabelThreadResult(applied=hasil.applied, removed=hasil.removed)
    )


# ══════════════════════════════════════════════════════════════════
# Tool 4: archive_thread
# ══════════════════════════════════════════════════════════════════


def archive_thread(
    args: ArchiveThreadArgs, ctx: ToolContext
) -> ToolResult[ArchiveThreadResult]:
    """Arsipkan thread (hapus label INBOX)."""
    client = _client(ctx)
    try:
        hasil = client.archive(thread_id=args.thread_id)
    except LookupError as exc:
        raise NotFoundError(f"Thread {args.thread_id!r} tidak ditemukan.") from exc

    return ToolResult.sukses(ArchiveThreadResult(archived=hasil.archived))


# ══════════════════════════════════════════════════════════════════
# Tool 5: create_draft_reply
# ══════════════════════════════════════════════════════════════════


def create_draft_reply(
    args: CreateDraftReplyArgs, ctx: ToolContext
) -> ToolResult[CreateDraftReplyResult]:
    """Buat draft balasan di thread yang sama.

    Penerima, subjek, In-Reply-To, dan References diambil dari header
    thread oleh KLIEN (kontrak 2, poin 4). Tool tidak menerima
    penerima/subjek sebagai argumen.
    """
    client = _client(ctx)

    # Body draft berasal dari LLM dan mungkin berisi placeholder yang
    # perlu dipulihkan sebelum dikirim ke Gmail. restore() di sini,
    # bukan di client, karena client tidak punya akses ke PiiMap.
    from app.privacy.redact import restore

    body_terpulihkan = restore(args.body, ctx.pii_map)

    try:
        hasil = client.create_draft(
            thread_id=args.thread_id, body=body_terpulihkan
        )
    except LookupError as exc:
        raise NotFoundError(f"Thread {args.thread_id!r} tidak ditemukan.") from exc

    return ToolResult.sukses(
        CreateDraftReplyResult(draft_id=hasil.draft_id)
    )


# ══════════════════════════════════════════════════════════════════
# Registrasi ke dispatcher
# ══════════════════════════════════════════════════════════════════


def register_all_tools() -> None:
    """Daftarkan 5 tool MVP ke dispatcher.

    Dipanggil sekali saat aplikasi start, atau di fixture tes.
    Idempoten: jika tool sudah terdaftar, tidak raise.
    """
    from app.agent import dispatcher as d

    existing = d.registered_tools()

    pasangan = [
        ("scan_emails", ScanEmailsArgs, scan_emails),
        ("fetch_thread", FetchThreadArgs, fetch_thread),
        ("label_thread", LabelThreadArgs, label_thread),
        ("archive_thread", ArchiveThreadArgs, archive_thread),
        ("create_draft_reply", CreateDraftReplyArgs, create_draft_reply),
    ]

    for nama, model, fn in pasangan:
        if nama not in existing:
            d.register_tool(nama, model, fn)


# Allowlist MVP: semua 5 tool. Setelah MVP, trash ditambahkan.
ALL_TOOLS_MVP: frozenset[str] = frozenset(
    {
        "scan_emails",
        "fetch_thread",
        "label_thread",
        "archive_thread",
        "create_draft_reply",
    }
)