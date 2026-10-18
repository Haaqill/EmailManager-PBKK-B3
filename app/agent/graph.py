"""Workflow LangGraph (M2, A).

STUB. Implementasi diisi di M2.
"""
from __future__ import annotations


class InboxGraph:
    """Workflow: fetch → classify → draft → review(interrupt) → execute → report.

    Akan diisi di M2:
    - state.py InboxState
    - checkpointer MemorySaver
    - node review memakai interrupt
    - UI melanjutkan dengan Command(resume=decisions)
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError("InboxGraph: diisi di M2 (A)")

    def invoke(self, *args, **kwargs):
        raise NotImplementedError("InboxGraph.invoke: diisi di M2 (A)")