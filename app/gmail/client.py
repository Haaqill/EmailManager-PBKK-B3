"""GmailAPIClient — klien Gmail asli (M1, B).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations


class GmailAPIClient:
    """Implementasi klien Gmail asli.

    Akan diisi di M1 (B):
    - daftar thread (scan_emails)
    - ambil thread (fetch_thread)
    - ubah label, buat label Kategori/* dan Prioritas/*
    - arsip (hapus label INBOX)
    - buat draft balasan
    - backoff 429/5xx dengan tenacity + jitter, maks 3x
    """

    def __init__(self, config=None) -> None:
        raise NotImplementedError("GmailAPIClient: diisi di M1 (B)")