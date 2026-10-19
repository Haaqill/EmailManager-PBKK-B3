"""MockGmailAPIClient — klien Gmail palsu (M1, B).

STUB. Implementasi diisi di M1.
"""
from __future__ import annotations


class MockGmailAPIClient:
    """Klien Gmail palsu yang membaca eval/dataset.json.

    Akan diisi di M1 (B):
    - baca eval/dataset.json (array JSON) → list thread
    - simpan perubahan label, arsip, draft di memori
    - antarmuka sama persis dengan GmailAPIClient
    - dipakai A untuk M2 tanpa Gmail
    """

    def __init__(self, dataset_path: str = "eval/dataset.json") -> None:
        raise NotImplementedError("MockGmailAPIClient: diisi di M1 (B)")