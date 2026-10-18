"""InboxState untuk workflow LangGraph (M2, A).

STUB. Implementasi diisi di M2.
"""
from __future__ import annotations

from typing import TypedDict


class InboxState(TypedDict, total=False):
    """State workflow. Akan diisi di M2:

    batch_id: str
    pii_map_ref: str           # batch_id saja, JANGAN pii_map
    threads: list[dict]
    plan: list[dict]           # list[PlanItem] setelah Pydantic
    decisions: list[dict]      # list[ReviewDecision]
    action_history: list[dict] # list[ActionRecord]
    report: dict
    error: str | None
    """