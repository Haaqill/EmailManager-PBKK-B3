"""JSONL logger teredaksi (M1, C).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations

import logging


def get_logger(name: str = "gmail_agent") -> logging.Logger:
    """STUB: kembalikan logger standar.

    C akan mengganti dengan:
    - formatter JSONL
    - redact argumen sebelum ditulis
    - tulis ke file log yang sudah ada di .gitignore
    - tidak pernah menulis teks asli atau isi PiiMap
    """
    return logging.getLogger(name)