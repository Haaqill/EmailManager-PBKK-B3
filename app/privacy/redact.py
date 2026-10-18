"""Redaksi PII — STUB sementara (C mengganti di M1).

Stub ini mengembalikan teks apa adanya agar B bisa menulis tool
sebelum redact() sungguhan selesai. C mengganti isi file ini di M1.
"""
from __future__ import annotations

from typing import Protocol


class PiiMap(Protocol):
    """Satu peta per batch. Hanya di memori.

    Implementasi nyata akan menyimpan:
    - nilai_asli -> placeholder (untuk redact)
    - placeholder -> nilai_asli (untuk restore)
    - set nilai rahasia yang tidak bisa dipulihkan

    TIDAK PERNAH masuk log, state, disk, atau prompt.
    """


class _StubPiiMap:
    """Implementasi sementara: peta kosong."""


def pii_map_for(batch_id: str) -> PiiMap:
    """STUB: kembalikan PiiMap kosong per batch_id."""
    return _StubPiiMap()


def redact(text: str, pii_map: PiiMap) -> str:
    """STUB: kembalikan teks apa adanya.

    C akan mengganti dengan regex email/nama/telepon/rahasia →
    placeholder <EMAIL_n>, <PERSON_n>, <PHONE_n>, [SECRET].
    """
    return text


def restore(text: str, pii_map: PiiMap) -> str:
    """STUB: kembalikan teks apa adanya."""
    return text


def html_to_text(html: str) -> str:
    """STUB: kembalikan HTML apa adanya.

    C akan mengganti dengan konversi HTML → teks polos,
    buang tracking pixel dan gambar base64.
    """
    return html