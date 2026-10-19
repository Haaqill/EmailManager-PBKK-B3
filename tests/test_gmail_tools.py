"""Tes untuk 5 tool Gmail MVP.

Memakai MockGmailAPIClient tiruan sederhana di dalam file ini,
sehingga tool bisa diuji SEBELUM MockGmailAPIClient sungguhan selesai.
Filosofi: uji kontrak tool (argumen, redaksi, error), bukan Gmail API.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent import dispatcher as d
from app.contracts import (
    ErrorCode,
    FatalToolError,
    NotFoundError,
    ToolContext,
    ToolResult,
)
from app.gmail.schemas import (
    GmailArchiveResult,
    GmailAttachment,
    GmailDraftResult,
    GmailLabelResult,
    GmailMessage,
    GmailThread,
    GmailThreadSummary,
)
from app.gmail.tools import (
    ALL_TOOLS_MVP,
    archive_thread,
    create_draft_reply,
    fetch_thread,
    label_thread,
    register_all_tools,
    scan_emails,
)


# ══════════════════════════════════════════════════════════════════
# MockGmailAPIClient tiruan
# ══════════════════════════════════════════════════════════════════


class MockGmail:
    """Implementasi minimal GmailClient untuk tes.

    Menyimpan data MENTAH; tool yang akan meredaksi.
    """

    def __init__(self) -> None:
        self.threads: dict[str, dict] = {}
        self.drafts: list[dict] = []
        self.labels_applied: list[dict] = []
        self.archived: list[str] = []
        self.list_threads_calls: list[dict] = []

    def tambah_thread(
        self,
        thread_id: str,
        *,
        subject: str,
        from_domain: str,
        snippet: str,
        messages: list[dict] | None = None,
        attachments: list[dict] | None = None,
        unread: bool = True,
        in_inbox: bool = True,
    ) -> None:
        self.threads[thread_id] = {
            "subject": subject,
            "from_domain": from_domain,
            "snippet": snippet,
            "messages": messages or [],
            "attachments": attachments or [],
            "unread": unread,
            "in_inbox": in_inbox,
            "date": "2026-10-13T08:15:00+07:00",
            "message_count": len(messages or []) or 1,
        }

    def list_threads(
        self,
        *,
        unread_only: bool,
        newer_than_days: int,
        in_inbox: bool,
        sender_domain: str,
        max_results: int,
    ) -> list[GmailThreadSummary]:
        self.list_threads_calls.append(
            {
                "unread_only": unread_only,
                "newer_than_days": newer_than_days,
                "in_inbox": in_inbox,
                "sender_domain": sender_domain,
                "max_results": max_results,
            }
        )
        hasil = []
        for tid, t in self.threads.items():
            if unread_only and not t["unread"]:
                continue
            if in_inbox and not t["in_inbox"]:
                continue
            if sender_domain and t["from_domain"] != sender_domain:
                continue
            hasil.append(
                GmailThreadSummary(
                    thread_id=tid,
                    subject=t["subject"],
                    from_domain=t["from_domain"],
                    snippet=t["snippet"],
                    date=t["date"],
                    message_count=t["message_count"],
                    has_attachments=bool(t["attachments"]),
                )
            )
            if len(hasil) >= max_results:
                break
        return hasil

    def get_thread(
        self, *, thread_id: str, max_messages: int
    ) -> GmailThread:
        if thread_id not in self.threads:
            raise LookupError(f"thread {thread_id} tidak ada")
        t = self.threads[thread_id]
        pesan = [
            GmailMessage(from_=m["from"], date=m["date"], body_text=m["body"])
            for m in t["messages"][-max_messages:]
        ]
        return GmailThread(
            thread_id=thread_id,
            subject=t["subject"],
            from_domain=t["from_domain"],
            messages=pesan,
            attachments=[
                GmailAttachment(
                    name=a["name"],
                    mime_type=a["mime_type"],
                    size_bytes=a["size_bytes"],
                )
                for a in t["attachments"]
            ],
        )

    def apply_labels(
        self, *, thread_id: str, category: str, priority: str, reason: str
    ) -> GmailLabelResult:
        if thread_id not in self.threads:
            raise LookupError(f"thread {thread_id} tidak ada")
        baru = [f"Kategori/{category}", f"Prioritas/{priority}"]
        # Simulasi hapus label lama Kategori/* dan Prioritas/*
        lama = self.threads[thread_id].get("labels", [])
        dihapus = [
            l for l in lama if l.startswith("Kategori/") or l.startswith("Prioritas/")
        ]
        self.labels_applied.append(
            {"thread_id": thread_id, "applied": baru, "removed": dihapus}
        )
        self.threads[thread_id]["labels"] = baru
        return GmailLabelResult(applied=baru, removed=dihapus)

    def archive(self, *, thread_id: str) -> GmailArchiveResult:
        if thread_id not in self.threads:
            raise LookupError(f"thread {thread_id} tidak ada")
        self.archived.append(thread_id)
        self.threads[thread_id]["in_inbox"] = False
        return GmailArchiveResult(archived=True)

    def create_draft(
        self, *, thread_id: str, body: str
    ) -> GmailDraftResult:
        if thread_id not in self.threads:
            raise LookupError(f"thread {thread_id} tidak ada")
        draft_id = f"draft-{len(self.drafts) + 1}"
        self.drafts.append(
            {"draft_id": draft_id, "thread_id": thread_id, "body": body}
        )
        return GmailDraftResult(draft_id=draft_id)


# ══════════════════════════════════════════════════════════════════
# Fixture
# ══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _bersihkan_registry():
    d.clear_registry()
    yield
    d.clear_registry()


@pytest.fixture
def pii_map():
    """PiiMap kosong — redact() stub mengembalikan teks apa adanya."""

    class _Map:
        pass

    return _Map()


@pytest.fixture
def client() -> MockGmail:
    return MockGmail()


@pytest.fixture
def ctx(client, pii_map) -> ToolContext:
    return ToolContext(
        batch_id="batch-test",
        pii_map=pii_map,
        allowed_tools=set(ALL_TOOLS_MVP),
        gmail_client=client,
    )


@pytest.fixture
def thread_lengkap(client: MockGmail) -> str:
    client.tambah_thread(
        "t1",
        subject="Pengumpulan Tugas 3 diperpanjang",
        from_domain="univ.ac.id",
        snippet="Batas pengumpulan Tugas 3 diundur ke Jumat pukul 23.59.",
        messages=[
            {
                "from": "Dr. Sari Wulandari <sari.w@univ.ac.id>",
                "date": "2026-10-13T08:15:00+07:00",
                "body": "Batas pengumpulan Tugas 3 diundur ke Jumat pukul 23.59.",
            }
        ],
        attachments=[
            {"name": "rubrik.pdf", "mime_type": "application/pdf", "size_bytes": 182344}
        ],
    )
    return "t1"


# ══════════════════════════════════════════════════════════════════
# scan_emails
# ══════════════════════════════════════════════════════════════════


def test_scan_emails_sukses_mengembalikan_thread(ctx, thread_lengkap):
    from app.gmail.schemas import ScanEmailsArgs

    hasil = scan_emails(ScanEmailsArgs(), ctx)
    assert hasil.ok is True
    assert len(hasil.data.threads) == 1
    assert hasil.data.threads[0].thread_id == "t1"

def test_scan_emails_menyusun_query_dari_filter(ctx, thread_lengkap):
    from app.gmail.schemas import ScanEmailsArgs

    hasil = scan_emails(
        ScanEmailsArgs(newer_than_days=3, in_inbox=True, unread_only=True),
        ctx,
    )
    assert "is:unread" in hasil.data.query
    assert "newer_than:3d" in hasil.data.query
    assert "in:inbox" in hasil.data.query


def test_scan_emails_meneruskan_domain_bersih_ke_client(
    ctx, client, thread_lengkap
):
    """sender_domain diteruskan ke client sudah dalam bentuk lowercase
    dan valid (setelah Pydantic)."""
    from app.gmail.schemas import ScanEmailsArgs

    client.list_threads_calls.clear()
    scan_emails(ScanEmailsArgs(sender_domain="UNIV.AC.ID"), ctx)
    call = client.list_threads_calls[-1]
    assert call["sender_domain"] == "univ.ac.id"
    

def test_bangun_query_menyusun_filter_dengan_benar():
    """_bangun_query menyusun query dari filter yang sudah valid."""
    from app.gmail.schemas import ScanEmailsArgs
    from app.gmail.tools import _bangun_query

    query = _bangun_query(
        ScanEmailsArgs(
            unread_only=True,
            newer_than_days=3,
            in_inbox=True,
            sender_domain="univ.ac.id",
        )
    )
    assert query == "is:unread newer_than:3d in:inbox from:@univ.ac.id"


def test_bangun_query_tanpa_domain():
    from app.gmail.schemas import ScanEmailsArgs
    from app.gmail.tools import _bangun_query

    query = _bangun_query(ScanEmailsArgs(unread_only=False, in_inbox=False))
    assert query == "newer_than:7d"


def test_sender_domain_tidak_valid_ditolak_pydantic():
    """Domain dengan karakter injeksi ditolak di Pydantic,
    bukan disaring diam-diam di _bangun_query."""
    from pydantic import ValidationError
    from app.gmail.schemas import ScanEmailsArgs

    for buruk in ["univ.ac.id; DROP TABLE", "DROP TABLE", "a b", "a;b", "a@b"]:
        with pytest.raises(ValidationError):
            ScanEmailsArgs(sender_domain=buruk)


def test_sender_domain_valid_diterima():
    from app.gmail.schemas import ScanEmailsArgs

    for baik in ["univ.ac.id", "mail.google.com", "a-b.co.id", ""]:
        args = ScanEmailsArgs(sender_domain=baik)
        assert args.sender_domain == baik.strip().lower()


def test_sender_domain_dinormalisasi_ke_lowercase():
    from app.gmail.schemas import ScanEmailsArgs

    args = ScanEmailsArgs(sender_domain="UNIV.AC.ID")
    assert args.sender_domain == "univ.ac.id"

    
def test_scan_emails_max_results_default_10(ctx, client):
    from app.gmail.schemas import ScanEmailsArgs

    scan_emails(ScanEmailsArgs(), ctx)
    assert client.list_threads_calls[-1]["max_results"] == 10


def test_scan_emails_redaksi_dipanggil(monkeypatch, ctx, thread_lengkap):
    """Pastikan redact() dipanggil untuk subject, snippet."""
    from app.gmail.schemas import ScanEmailsArgs
    from app.privacy import redact as modul_redact

    dipanggil = {"n": 0}

    def _redact_spy(text, pii_map):
        dipanggil["n"] += 1
        return text

    monkeypatch.setattr(modul_redact, "redact", _redact_spy)

    scan_emails(ScanEmailsArgs(), ctx)
    assert dipanggil["n"] >= 2  # subject + snippet minimal


def test_scan_emails_tanpa_gmail_client_raise_fatal(pii_map):
    from app.gmail.schemas import ScanEmailsArgs

    ctx = ToolContext(
        batch_id="b", pii_map=pii_map, allowed_tools=set(ALL_TOOLS_MVP),
        gmail_client=None,
    )
    with pytest.raises(FatalToolError, match="gmail_client"):
        scan_emails(ScanEmailsArgs(), ctx)


# ══════════════════════════════════════════════════════════════════
# fetch_thread
# ══════════════════════════════════════════════════════════════════


def test_fetch_thread_sukses(ctx, thread_lengkap):
    from app.gmail.schemas import FetchThreadArgs

    hasil = fetch_thread(FetchThreadArgs(thread_id="t1"), ctx)
    assert hasil.ok is True
    assert hasil.data.thread.thread_id == "t1"
    assert len(hasil.data.thread.messages) == 1


def test_fetch_thread_max_messages_dihormati(ctx, client):
    from app.gmail.schemas import FetchThreadArgs

    client.tambah_thread(
        "t2",
        subject="Multi pesan",
        from_domain="univ.ac.id",
        snippet="...",
        messages=[
            {"from": "a@x.com", "date": "2026-10-01", "body": f"pesan {i}"}
            for i in range(10)
        ],
    )
    hasil = fetch_thread(
        FetchThreadArgs(thread_id="t2", max_messages=3), ctx
    )
    assert len(hasil.data.thread.messages) == 3


def test_fetch_thread_tidak_ada_raise_not_found(ctx):
    from app.gmail.schemas import FetchThreadArgs

    with pytest.raises(NotFoundError, match="tidak ditemukan"):
        fetch_thread(FetchThreadArgs(thread_id="tidak-ada"), ctx)


def test_fetch_thread_redaksi_dipanggil(monkeypatch, ctx, thread_lengkap):
    from app.gmail.schemas import FetchThreadArgs
    from app.privacy import redact as modul_redact

    dipanggil = {"n": 0}

    def _redact_spy(text, pii_map):
        dipanggil["n"] += 1
        return text

    monkeypatch.setattr(modul_redact, "redact", _redact_spy)
    fetch_thread(FetchThreadArgs(thread_id="t1"), ctx)
    # subject + from_ + body_text = minimal 3
    assert dipanggil["n"] >= 3


# ══════════════════════════════════════════════════════════════════
# label_thread
# ══════════════════════════════════════════════════════════════════


def test_label_thread_sukses(ctx, client, thread_lengkap):
    from app.gmail.schemas import LabelThreadArgs

    hasil = label_thread(
        LabelThreadArgs(
            thread_id="t1",
            category="Tugas",
            priority="Mendesak",
            reason="Perlu tindakan",
        ),
        ctx,
    )
    assert hasil.ok is True
    assert "Kategori/Tugas" in hasil.data.applied
    assert "Prioritas/Mendesak" in hasil.data.applied
    assert len(client.labels_applied) == 1


def test_label_thread_menghapus_label_lama(ctx, client, thread_lengkap):
    from app.gmail.schemas import LabelThreadArgs

    # Pasang label pertama
    label_thread(
        LabelThreadArgs(
            thread_id="t1", category="Tugas", priority="Normal", reason="x"
        ),
        ctx,
    )
    # Ganti dengan label baru
    label_thread(
        LabelThreadArgs(
            thread_id="t1", category="Akademik", priority="Mendesak", reason="y"
        ),
        ctx,
    )
    # Label lama harus dihapus
    assert "Kategori/Tugas" in client.labels_applied[1]["removed"]
    assert "Prioritas/Normal" in client.labels_applied[1]["removed"]


def test_label_thread_tidak_ada_raise_not_found(ctx):
    from app.gmail.schemas import LabelThreadArgs

    with pytest.raises(NotFoundError):
        label_thread(
            LabelThreadArgs(
                thread_id="tidak-ada", category="Tugas", priority="Normal", reason="x"
            ),
            ctx,
        )


# ══════════════════════════════════════════════════════════════════
# archive_thread
# ══════════════════════════════════════════════════════════════════


def test_archive_thread_sukses(ctx, client, thread_lengkap):
    from app.gmail.schemas import ArchiveThreadArgs

    hasil = archive_thread(ArchiveThreadArgs(thread_id="t1"), ctx)
    assert hasil.ok is True
    assert hasil.data.archived is True
    assert "t1" in client.archived


def test_archive_thread_tidak_ada_raise_not_found(ctx):
    from app.gmail.schemas import ArchiveThreadArgs

    with pytest.raises(NotFoundError):
        archive_thread(ArchiveThreadArgs(thread_id="tidak-ada"), ctx)


# ══════════════════════════════════════════════════════════════════
# create_draft_reply
# ══════════════════════════════════════════════════════════════════


def test_create_draft_reply_sukses(ctx, client, thread_lengkap):
    from app.gmail.schemas import CreateDraftReplyArgs

    hasil = create_draft_reply(
        CreateDraftReplyArgs(thread_id="t1", body="Terima kasih."),
        ctx,
    )
    assert hasil.ok is True
    assert hasil.data.draft_id.startswith("draft-")
    assert client.drafts[-1]["body"] == "Terima kasih."


def test_create_draft_reply_restore_dipanggil(monkeypatch, ctx, client, thread_lengkap):
    """Body dari LLM berisi placeholder, harus di-restore sebelum ke client."""
    from app.gmail.schemas import CreateDraftReplyArgs
    from app.privacy import redact as modul_redact

    dipanggil = {"n": 0}

    def _restore_spy(text, pii_map):
        dipanggil["n"] += 1
        return text.replace("<PERSON_1>", "Dr. Sari")

    monkeypatch.setattr(modul_redact, "restore", _restore_spy)

    create_draft_reply(
        CreateDraftReplyArgs(
            thread_id="t1", body="Halo <PERSON_1>, terima kasih."
        ),
        ctx,
    )

    # restore dipanggil sekali
    assert dipanggil["n"] == 1
    # body yang diterima client sudah dipulihkan
    assert client.drafts[-1]["body"] == "Halo Dr. Sari, terima kasih."

def test_create_draft_reply_tidak_ada_raise_not_found(ctx):
    from app.gmail.schemas import CreateDraftReplyArgs

    with pytest.raises(NotFoundError):
        create_draft_reply(
            CreateDraftReplyArgs(thread_id="tidak-ada", body="x"), ctx
        )


# ══════════════════════════════════════════════════════════════════
# Registrasi ke dispatcher
# ══════════════════════════════════════════════════════════════════


def test_register_all_tools_mendaftarkan_lima_tool():
    register_all_tools()
    terdaftar = d.registered_tools()
    assert terdaftar == set(ALL_TOOLS_MVP)


def test_register_all_tools_idempoten():
    register_all_tools()
    register_all_tools()  # tidak raise
    assert len(d.registered_tools()) == 5


def test_integrasi_dispatch_scan_emails(ctx, thread_lengkap):
    register_all_tools()
    hasil = d.dispatch("scan_emails", {"unread_only": True}, ctx)
    assert hasil.ok is True
    # hasil.data adalah ScanEmailsResult, bukan dict
    assert len(hasil.data.threads) == 1
    assert hasil.data.threads[0].thread_id == "t1"

def test_integrasi_dispatch_allowlist_memblokir_trash(ctx):
    """MVP tidak mengizinkan trash_thread. Dispatcher harus menolak."""
    register_all_tools()
    hasil = d.dispatch("trash_thread", {"thread_id": "t1"}, ctx)
    assert hasil.ok is False
    assert hasil.error_code == ErrorCode.NOT_ALLOWED