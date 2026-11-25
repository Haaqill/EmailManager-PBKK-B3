"""Rubrik klasifikasi di SYSTEM_CLASSIFY dan label dataset yang mengikutinya.

Label eval/dataset.json adalah kunci jawaban evaluasi: label diturunkan dari rubrik dan isi
email, bukan dari jawaban model. Tes ini menjaga keduanya tetap sejalan.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.prompts import ClassificationOutput, SYSTEM_CLASSIFY, build_thread_message
from app.gmail.mock_client import load_dataset

DATASET = "eval/dataset.json"


def _thread(date: str) -> dict:
    return {
        "thread_id": "t", "subject": "s", "from_domain": "kampus.example", "attachments": [],
        "messages": [{"from": "<PERSON_1>", "date": date, "body_text": "isi"}],
    }


def test_rubrik_prioritas_lengkap_dengan_patokan_tanggal():
    rubrik = SYSTEM_CLASSIFY.split("- priority", 1)[1].split("- action:", 1)[0]
    for level in ("Mendesak:", "Normal:", "Nanti:"):
        assert level in rubrik
    assert "tanggal pesan terakhir di thread" in rubrik
    assert "Promosi dan Spam selalu Nanti" in rubrik


def test_rubrik_mempertegas_pengumuman_dan_spam():
    kategori = SYSTEM_CLASSIFY.split("- category:", 1)[1].split("- priority", 1)[0]
    assert "perubahan ruang atau jadwal kuliah, adalah Pengumuman" in kategori
    assert "kata sandi, kode verifikasi" in kategori
    assert "Notifikasi keamanan yang hanya memberi" in kategori


def test_tanggal_pesan_diberi_nama_hari():
    pesan = build_thread_message(_thread("2026-10-18T08:15:00+07:00"))
    assert "Tanggal: 2026-10-18T08:15:00+07:00 (Minggu)" in pesan


def test_tanggal_tidak_valid_dibiarkan_apa_adanya():
    pesan = build_thread_message(_thread("kemarin sore"))
    assert "Tanggal: kemarin sore\n" in pesan


def test_label_dataset_mengikuti_rubrik():
    rows = {r.id: r for r in load_dataset(DATASET)}
    # t001: tenggat diundur ke Jumat, 5 hari setelah pesan (Minggu) -> Normal.
    assert rows["t001"].expected.priority == "Normal"
    # t002: bimbingan Selasa, sehari setelah pesan (Senin), dan minta konfirmasi -> Mendesak.
    assert rows["t002"].expected.priority == "Mendesak"
    # t003: perubahan ruang dari sekretariat fakultas -> Pengumuman tanpa tindakan.
    t003 = rows["t003"].expected
    assert (t003.category, t003.priority, t003.action) == ("Pengumuman", "Nanti", "archive")
    # t006: meminta kata sandi dan kode verifikasi lewat domain tiruan -> Spam.
    t006 = rows["t006"]
    assert t006.expected.category == "Spam"
    body = " ".join(m.body for m in t006.messages).lower()
    assert "password" in body and "verification code" in body


def test_prioritas_nanti_menolak_kebutuhan_balasan():
    with pytest.raises(
        ValidationError,
        match="Prioritas Nanti tidak boleh disertai needs_reply",
    ):
        ClassificationOutput(
            thread_id="t",
            summary="ringkasan",
            category="Tugas",
            priority="Nanti",
            action="keep",
            needs_reply=True,
            reason="perlu balasan",
        )


@pytest.mark.parametrize("category", ["Promosi", "Spam"])
def test_promosi_dan_spam_tetap_boleh_nanti(category):
    result = ClassificationOutput(
        thread_id="t",
        summary="ringkasan",
        category=category,
        priority="Nanti",
        action="archive",
        needs_reply=False,
        reason="tidak perlu balasan",
    )
    assert result.priority == "Nanti"


@pytest.mark.parametrize(
    ("priority", "needs_reply"),
    [("Normal", True), ("Mendesak", True), ("Nanti", False)],
)
def test_kombinasi_prioritas_dan_balasan_yang_sah(priority, needs_reply):
    result = ClassificationOutput(
        thread_id="t",
        summary="ringkasan",
        category="Tugas",
        priority=priority,
        action="keep",
        needs_reply=needs_reply,
        reason="sesuai rubrik",
    )
    assert result.needs_reply is needs_reply


def test_label_dataset_tidak_melanggar_prioritas_nanti_dan_balasan():
    assert not [
        row.id
        for row in load_dataset(DATASET)
        if row.expected.priority == "Nanti" and row.expected.needs_reply
    ]
