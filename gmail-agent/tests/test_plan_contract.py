"""Tes kontrak Laravel <-> Python tahap 1 (app/privacy/contract.py).

Semua data fiktif.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.privacy.contract import (
    Draft,
    PlanItem,
    PlanSnapshot,
    RawThreadMeta,
    ThreadInfo,
    build_plan_snapshot,
)
from app.privacy.redact import PIIRedactor
from export_plan_schema import SCHEMA_PATH, render_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_PATTERN = re.compile(r"<(PERSON|EMAIL|PHONE)_")


@pytest.fixture
def pii_map() -> PIIRedactor:
    peta = PIIRedactor(keep_domain=False)   # sama dengan pii_map_for()
    yield peta
    peta.clear()


def _raw(thread_id: str = "t001", **kw) -> RawThreadMeta:
    data = {
        "thread_id": thread_id,
        "subject": "Bimbingan skripsi Rina Kartika",
        "from": '"Dr. Sari Wulandari" <sari.w@univ.ac.id>',
        "date": "2026-11-15T09:30:00+07:00",
        "attachments": [{"name": "jadwal.pdf", "mime_type": "application/pdf", "size_bytes": 2048}],
    }
    data.update(kw)
    return RawThreadMeta.model_validate(data)


def _plan_item(thread_id: str = "t001", **kw) -> dict:
    item = {
        "thread_id": thread_id,
        "summary": "ringkasan",
        "category": "Akademik",
        "priority": "Mendesak",
        "action": "keep",
        "needs_reply": False,
        "draft_body": None,
        "reason": "Dosen meminta konfirmasi jadwal.",
    }
    item.update(kw)
    return item


def _thread() -> ThreadInfo:
    return ThreadInfo(subject="s", from_name="n", from_domain="d.id", date="2026-11-15")


# (1) placeholder di reason dan draft_body dipulihkan
def test_placeholder_di_reason_dan_draft_dipulihkan(pii_map):
    person = pii_map.register_person("Sari Wulandari")
    phone = pii_map.redact_text("0812-3456-7890")
    plan = [_plan_item(
        reason=f"{person} meminta konfirmasi.",
        needs_reply=True,
        draft_body=f"Yth. {person}, saya bisa dihubungi di {phone}.",
    )]
    snap = build_plan_snapshot(plan, {"t001": _raw()}, pii_map, plan_version=1)
    item = snap.items[0]
    assert item.reason == "Sari Wulandari meminta konfirmasi."
    assert item.draft is not None
    assert item.draft.body == "Yth. Sari Wulandari, saya bisa dihubungi di 0812-3456-7890."
    assert item.action == "draft_reply"
    assert item.warnings == []


# (2) thread{} dan draft.to/subject dari metadata asli
def test_thread_dan_header_draft_dari_metadata_asli(pii_map):
    plan = [_plan_item(needs_reply=True, draft_body="Baik, terima kasih.")]
    raw = _raw(reply_to="Sekretariat Prodi <prodi@univ.ac.id>")
    item = build_plan_snapshot(plan, {"t001": raw}, pii_map, plan_version=1).items[0]
    assert item.thread.subject == "Bimbingan skripsi Rina Kartika"
    assert item.thread.from_name == "Dr. Sari Wulandari"
    assert item.thread.from_domain == "univ.ac.id"
    assert item.thread.date == "2026-11-15T09:30:00+07:00"
    assert item.thread.attachments[0].model_dump() == {
        "filename": "jadwal.pdf", "type": "application/pdf", "size": 2048,
    }
    assert item.draft.to == "Sekretariat Prodi <prodi@univ.ac.id>"
    assert item.draft.subject == "Re: Bimbingan skripsi Rina Kartika"


def test_draft_to_memakai_from_bila_tanpa_reply_to(pii_map):
    plan = [_plan_item(needs_reply=True, draft_body="Baik.")]
    item = build_plan_snapshot(plan, {"t001": _raw(subject="Re: Jadwal")}, pii_map, 1).items[0]
    assert item.draft.to == '"Dr. Sari Wulandari" <sari.w@univ.ac.id>'   # RFC 5322: titik dikutip
    assert item.draft.subject == "Re: Jadwal"


def test_pemetaan_nilai_lama_ke_kabel(pii_map):
    plan = [
        _plan_item("t001", action="keep"),
        _plan_item("t002", category="Promosi", priority="Nanti", action="archive"),
        _plan_item("t003", action="trash"),
    ]
    raws = {t: _raw(t) for t in ("t001", "t002", "t003")}
    items = build_plan_snapshot(plan, raws, pii_map, plan_version=3).items
    assert [i.item_id for i in items] == ["i_01", "i_02", "i_03"]
    assert [i.action for i in items] == ["label_only", "archive", "trash"]
    assert [i.requires_confirmation for i in items] == [False, False, True]
    assert (items[1].category, items[1].priority) == ("promosi", "nanti")
    assert all(i.confidence is None for i in items)   # klasifikasi belum memberi confidence


# (3) placeholder yang tidak terselesaikan
def test_placeholder_tak_terselesaikan_memberi_warning(pii_map):
    plan = [_plan_item(reason="Teruskan ke <PERSON_9>.", needs_reply=True,
                       draft_body="Hubungi <PHONE_4> atau <EMAIL_7>.")]
    item = build_plan_snapshot(plan, {"t001": _raw()}, pii_map, 1).items[0]
    codes = [w.code for w in item.warnings]
    assert codes == ["UNRESOLVED_PLACEHOLDER", "UNRESOLVED_PLACEHOLDER"]
    assert "reason" in item.warnings[0].message and "PERSON" in item.warnings[0].message
    assert "draft.body" in item.warnings[1].message
    assert "EMAIL, PHONE" in item.warnings[1].message
    for w in item.warnings:   # pesan hanya menyebut jenis, bukan placeholder mentah
        assert "<" not in w.message


def test_secret_bukan_placeholder_tak_terselesaikan(pii_map):
    plan = [_plan_item(reason="Kode [SECRET] tidak ditampilkan.")]
    item = build_plan_snapshot(plan, {"t001": _raw()}, pii_map, 1).items[0]
    assert item.warnings == []


# (4) serialisasi bebas pii_map dan placeholder
def test_json_tanpa_pii_map_dan_tanpa_placeholder(pii_map):
    person = pii_map.register_person("Sari Wulandari")
    email = pii_map.redact_text("sari.w@univ.ac.id")
    plan = [_plan_item(reason=f"Dari {person}", needs_reply=True,
                       draft_body=f"Balas ke {email}, salam untuk {person}.")]
    payload = build_plan_snapshot(plan, {"t001": _raw()}, pii_map, 1).model_dump_json()
    data = json.loads(payload)

    def keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from keys(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from keys(v)

    all_keys = set(keys(data))
    assert not all_keys & {"pii_map", "_originals", "_by_value", "originals", "mapping"}
    assert not PLACEHOLDER_PATTERN.search(payload)
    assert "PIIRedactor" not in payload
    # pasangan placeholder -> nilai dari peta tidak ikut keluar
    assert f'"{person}"' not in payload and person not in payload


# (5) trash dan draft
def test_trash_wajib_konfirmasi():
    base = dict(item_id="i_01", thread_id="t", thread=_thread(), category="spam",
                priority="nanti", reason="r")
    assert PlanItem(**base, action="trash", requires_confirmation=True).requires_confirmation
    with pytest.raises(ValidationError):
        PlanItem(**base, action="trash", requires_confirmation=False)
    with pytest.raises(ValidationError):
        PlanItem(**base, action="archive", requires_confirmation=True)


def test_draft_hanya_untuk_draft_reply():
    base = dict(item_id="i_01", thread_id="t", thread=_thread(), category="tugas",
                priority="normal", reason="r", requires_confirmation=False)
    draft = Draft(to="a <a@b.id>", subject="Re: x", body="isi")
    assert PlanItem(**base, action="draft_reply", draft=draft).draft == draft
    with pytest.raises(ValidationError):
        PlanItem(**base, action="draft_reply")
    with pytest.raises(ValidationError):
        PlanItem(**base, action="label_only", draft=draft)


def test_arsip_dengan_draft_menjadi_draft_reply_also_archive(pii_map):
    plan = [
        _plan_item("t001", action="archive", needs_reply=True, draft_body="Terima kasih."),
        _plan_item("t002", action="keep", needs_reply=True, draft_body="Baik."),
        _plan_item("t003", action="archive"),
    ]
    raws = {t: _raw(t) for t in ("t001", "t002", "t003")}
    items = build_plan_snapshot(plan, raws, pii_map, 1).items
    assert [(i.action, i.also_archive) for i in items] == [
        ("draft_reply", True), ("draft_reply", False), ("archive", False),
    ]


def test_also_archive_hanya_untuk_draft_reply():
    base = dict(item_id="i_01", thread_id="t", thread=_thread(), category="tugas",
                priority="normal", reason="r", requires_confirmation=False)
    draft = Draft(to="a <a@b.id>", subject="Re: x", body="isi")
    assert PlanItem(**base, action="draft_reply", draft=draft, also_archive=True).also_archive
    for action in ("label_only", "archive"):
        with pytest.raises(ValidationError):
            PlanItem(**base, action=action, also_archive=True)
    with pytest.raises(ValidationError):
        PlanItem(**{**base, "requires_confirmation": True}, action="trash", also_archive=True)


def test_trash_tidak_membawa_draft(pii_map):
    plan = [_plan_item(action="trash", needs_reply=True, draft_body="x")]
    item = build_plan_snapshot(plan, {"t001": _raw()}, pii_map, 1).items[0]
    assert item.action == "trash" and item.draft is None


# (6) confidence
@pytest.mark.parametrize("value", [-0.01, 1.01, 5])
def test_confidence_di_luar_rentang_ditolak(value):
    with pytest.raises(ValidationError):
        PlanItem(item_id="i_01", thread_id="t", thread=_thread(), category="tugas",
                 priority="normal", action="label_only", reason="r",
                 confidence=value, requires_confirmation=False)


@pytest.mark.parametrize("value", [0, 0.5, 1, None])
def test_confidence_dalam_rentang_diterima(value):
    item = PlanItem(item_id="i_01", thread_id="t", thread=_thread(), category="tugas",
                    priority="normal", action="label_only", reason="r",
                    confidence=value, requires_confirmation=False)
    assert item.confidence == value


# (7) drift skema
def test_skema_tercatat_sama_dengan_ekspor():
    assert SCHEMA_PATH.exists(), "jalankan: python export_plan_schema.py"
    recorded = SCHEMA_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert recorded == render_schema(), "skema berubah; jalankan: python export_plan_schema.py"


def test_fixture_laravel_sesuai_skema():
    fixture = REPO_ROOT / "tests" / "Fixtures" / "agent" / "batch_awaiting_review.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    PlanSnapshot.model_validate(payload["plan"])
