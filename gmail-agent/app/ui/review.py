"""Logika tabel review tanpa Streamlit (D), supaya bisa dites terpisah.

- Tampilan memakai teks yang sudah di-restore (aplikasi lokal, data milik pengguna).
- Draft yang diedit pengguna diredaksi ulang sebelum masuk ReviewDecision,
  supaya state checkpoint tetap bebas PII; tool create_draft_reply memulihkannya
  lagi tepat sebelum disimpan ke Gmail.
"""
from __future__ import annotations

from typing import Any

from app.contracts import PlanItem, ReviewDecision
from app.privacy.redact import redact, restore

EDITABLE = ("kategori", "prioritas", "aksi", "draft")


def plan_to_rows(plan: list[PlanItem], pii_map: Any) -> list[dict]:
    return [
        {
            "setujui": True,
            "thread_id": p.thread_id,
            "ringkasan": restore(p.summary, pii_map),
            "kategori": p.category,
            "prioritas": p.priority,
            "aksi": p.action,
            "draft": restore(p.draft_body, pii_map) if p.draft_body else "",
            "alasan": restore(p.reason, pii_map),
        }
        for p in plan
    ]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""   # sel kosong dari data_editor bisa NaN/None


def rows_to_decisions(rows: list[dict], plan: list[PlanItem], pii_map: Any) -> list[ReviewDecision]:
    """Baris tabel → ReviewDecision. Raise ValueError jika hasil edit melanggar kontrak."""
    original = {r["thread_id"]: r for r in plan_to_rows(plan, pii_map)}
    by_id = {p.thread_id: p for p in plan}
    decisions = []
    for row in rows:
        tid = row["thread_id"]
        if tid not in by_id:
            continue
        if not row.get("setujui"):
            decisions.append(ReviewDecision(thread_id=tid, status="rejected"))
            continue
        before = original[tid]
        if all(_text(row.get(k)) == _text(before[k]) for k in EDITABLE):
            decisions.append(ReviewDecision(thread_id=tid, status="approved"))
            continue
        item = by_id[tid]
        draft = _text(row.get("draft")).strip()
        if draft == _text(before["draft"]):
            draft_body = item.draft_body
        else:
            draft_body = redact(draft, pii_map) if draft else None
        try:
            edited = item.model_copy(update={
                "category": row["kategori"], "priority": row["prioritas"], "action": row["aksi"],
                "draft_body": draft_body, "needs_reply": draft_body is not None,
            })
            edited = PlanItem.model_validate(edited.model_dump())
        except ValueError as exc:
            raise ValueError(f"{tid}: {exc}") from None
        decisions.append(ReviewDecision(thread_id=tid, status="edited", edited=edited))
    return decisions


def report_lines(report: dict) -> list[str]:
    lines = [
        f"{report['approved']} thread disetujui, {report['rejected']} ditolak "
        f"(dari {report['planned']} rencana, {report['threads']} thread dibaca).",
        f"{report['actions_ok']} aksi berhasil, {report['actions_failed']} gagal.",
    ]
    for tool, stat in sorted(report.get("per_tool", {}).items()):
        lines.append(f"- {tool}: {stat['ok']} berhasil, {stat['gagal']} gagal")
    return lines
