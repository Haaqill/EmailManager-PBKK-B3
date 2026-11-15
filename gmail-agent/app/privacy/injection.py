"""Pembungkus <email_content> untuk pertahanan prompt injection (M1, C).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations


def wrap_email_content(text: str) -> str:
    """STUB: kembalikan teks apa adanya.

    C akan mengganti dengan:
    - bungkus teks dengan <email_content>...</email_content>
    - escape tag penutup </email_content> di dalam isi
      supaya isi tidak bisa keluar dari pembungkus
    """
    return text