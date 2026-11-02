"""InboxState untuk workflow LangGraph (A).

State hanya berisi data TEREDAKSI dan tipe sederhana (dict/list), supaya
aman disimpan checkpointer. PiiMap TIDAK PERNAH masuk state; node mengambilnya
lagi dengan pii_map_for(batch_id).
"""
from __future__ import annotations

from typing import TypedDict


class InboxState(TypedDict, total=False):
    batch_id: str
    batch_size: int
    threads: list[dict]          # FetchThreadResult.thread teredaksi (model_dump by_alias)
    classifications: list[dict]  # ClassificationOutput yang lolos validasi
    drafts: dict[str, str]       # thread_id -> body draft (teredaksi)
    plan: list[dict]             # PlanItem.model_dump()
    decisions: list[dict]        # ReviewDecision.model_dump(), diisi UI lewat update_state
    action_history: list[dict]   # ActionRecord.model_dump()
    errors: list[dict]           # {"thread_id", "stage", "message"}
    report: dict
