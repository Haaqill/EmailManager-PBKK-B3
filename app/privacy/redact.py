"""STUB sementara — C akan mengganti ini di M1."""
from typing import Protocol

class PiiMap(Protocol): ...

def redact(text: str, pii_map: PiiMap) -> str:
    """Sementara: kembalikan apa adanya agar B bisa maju."""
    return text

def restore(text: str, pii_map: PiiMap) -> str:
    return text

def html_to_text(html: str) -> str:
    return html