"""Tes kontrak 3 (redaksi PII): fungsi yang dipakai B, A, dan D.

Semua data sintetis. Tes 20 email (gate M1) ditulis C terpisah.
"""
from __future__ import annotations

from app.privacy.redact import (
    SECRET,
    html_to_text,
    pii_map_for,
    redact,
    release_pii_map,
    restore,
)

EMAIL = (
    "Halo, Sari Wulandari di sini. Hubungi sari.w@univ.ac.id "
    "atau 0812-3456-7890 sebelum Jumat."
)


def test_redact_menyembunyikan_email_dan_telepon():
    peta = pii_map_for("t-redact")
    hasil = redact(EMAIL, peta)
    assert "sari.w@univ.ac.id" not in hasil
    assert "0812-3456-7890" not in hasil
    assert "<EMAIL_1>" in hasil      # tanpa domain, sesuai kontrak
    assert "<PHONE_1>" in hasil
    release_pii_map("t-redact")


def test_nama_dari_header_ikut_teredaksi_di_isi():
    peta = pii_map_for("t-nama")
    redact("Dr. Sari Wulandari <sari.w@univ.ac.id>", peta)
    hasil = redact("Terima kasih, Sari Wulandari.", peta)
    assert "Sari Wulandari" not in hasil
    assert "<PERSON_" in hasil
    release_pii_map("t-nama")


def test_bolak_balik_utuh():
    peta = pii_map_for("t-bolak")
    assert restore(redact(EMAIL, peta), peta) == EMAIL
    release_pii_map("t-bolak")


def test_nilai_sama_mendapat_placeholder_sama():
    peta = pii_map_for("t-sama")
    a = redact("Dari sari.w@univ.ac.id", peta)
    b = redact("Balas ke sari.w@univ.ac.id ya", peta)
    assert a.split()[-1] == b.split()[2] == "<EMAIL_1>"
    release_pii_map("t-sama")


def test_rahasia_tidak_pernah_kembali():
    peta = pii_map_for("t-rahasia")
    teks = "password: budi2026\ntoken: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    hasil = redact(teks, peta)
    assert "budi2026" not in hasil
    assert "ghp_" not in hasil
    assert SECRET in hasil
    pulih = restore(hasil, peta)
    assert "budi2026" not in pulih and "ghp_" not in pulih
    release_pii_map("t-rahasia")


def test_peta_sama_dalam_batch_dan_terpisah_antar_batch():
    assert pii_map_for("b1") is pii_map_for("b1")
    a, b = pii_map_for("b1"), pii_map_for("b2")
    redact("Dari sari.w@univ.ac.id", a)
    # batch lain tidak bisa memulihkan placeholder batch b1
    assert restore("<EMAIL_1>", b) == "<EMAIL_1>"
    release_pii_map("b1")
    release_pii_map("b2")


def test_release_menghapus_peta():
    peta = pii_map_for("t-release")
    redact("Dari sari.w@univ.ac.id", peta)
    release_pii_map("t-release")
    assert pii_map_for("t-release") is not peta
    release_pii_map("t-release")


def test_peta_tidak_bocor_lewat_repr():
    peta = pii_map_for("t-repr")
    redact(EMAIL, peta)
    assert "sari.w" not in repr(peta)
    assert "Wulandari" not in repr(peta)
    release_pii_map("t-repr")


def test_html_to_text_membuang_pixel_dan_script():
    html = '<p>Halo</p><img src="https://t.example/p.gif" width="1"><script>x()</script>'
    hasil = html_to_text(html)
    assert "Halo" in hasil
    assert "p.gif" not in hasil
    assert "x()" not in hasil
