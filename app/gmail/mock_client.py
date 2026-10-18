"""MockGmailAPIClient — klien Gmail palsu (M1, B).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations


class MockGmailAPIClient:
    """Klien Gmail palsu yang membaca eval/dataset.jsonl.

    Akan diisi di M1 (B):
    - baca eval/dataset.jsonl → list thread
    - simpan perubahan label, arsip, draft di memori
    - antarmuka sama persis dengan GmailAPIClient
    - dipakai A untuk M2 tanpa Gmail
    """

    def __init__(self, dataset_path: str = "eval/dataset.jsonl") -> None:
        raise NotImplementedError("MockGmailAPIClient: diisi di M1 (B)")