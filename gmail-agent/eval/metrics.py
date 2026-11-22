"""Metrik evaluasi klasifikasi per tingkat confidence.

Fungsi murni tanpa jaringan dan tanpa isi email: masukannya hanya label hasil klasifikasi
(category, priority, action, needs_reply, confidence) dan label `expected` dari dataset.

Pertanyaan yang dijawab: apakah item berlevel `tinggi` memang lebih sering benar daripada
`sedang`, dan `sedang` daripada `rendah`? Angka ini deskriptif saja. Dengan dataset kecil,
satu thread bisa menggeser akurasi satu level puluhan persen, jadi selalu baca bersama `n`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from app.contracts import CONFIDENCE_LEVELS

NO_LEVEL = "kosong"   # confidence null / tidak valid
LEVEL_KEYS: tuple[str, ...] = (*CONFIDENCE_LEVELS, NO_LEVEL)
FIELDS = ("category", "priority", "action", "needs_reply")


@dataclass(frozen=True)
class Record:
    """Hasil satu thread pada satu putaran. Tidak menyimpan summary/reason (turunan isi email)."""

    thread_id: str
    is_injection: bool
    classified: bool                 # False: klasifikasi gagal (error/tool tidak dipanggil)
    confidence: str | None = None
    category_ok: bool = False
    priority_ok: bool = False
    action_ok: bool = False
    needs_reply_ok: bool = False
    predicted: dict[str, Any] | None = None   # hanya label, bukan teks
    expected: dict[str, Any] | None = None

    @property
    def level(self) -> str:
        return self.confidence if self.confidence in CONFIDENCE_LEVELS else NO_LEVEL

    @property
    def both_ok(self) -> bool:
        """Kategori dan aksi sama-sama benar: dua hal yang dinilai confidence."""
        return self.category_ok and self.action_ok

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "level": self.level, "both_ok": self.both_ok}


def compare(thread_id: str, prediction: Mapping[str, Any] | None,
            expected: Mapping[str, Any], *, is_injection: bool = False) -> Record:
    """Bandingkan satu keluaran ClassificationOutput (dict) dengan label expected."""
    exp = {f: expected[f] for f in FIELDS}
    if prediction is None:
        return Record(thread_id=thread_id, is_injection=is_injection, classified=False,
                      expected=exp)
    pred = {f: prediction.get(f) for f in FIELDS}
    raw = prediction.get("confidence")
    return Record(
        thread_id=thread_id,
        is_injection=is_injection,
        classified=True,
        confidence=raw if raw in CONFIDENCE_LEVELS else None,
        category_ok=pred["category"] == exp["category"],
        priority_ok=pred["priority"] == exp["priority"],
        action_ok=pred["action"] == exp["action"],
        needs_reply_ok=pred["needs_reply"] == exp["needs_reply"],
        predicted=pred,
        expected=exp,
    )


def _rate(hits: int, n: int) -> float | None:
    return round(hits / n, 4) if n else None


def _bucket(records: list[Record]) -> dict[str, Any]:
    n = len(records)
    return {
        "n": n,
        "category": _rate(sum(r.category_ok for r in records), n),
        "action": _rate(sum(r.action_ok for r in records), n),
        "both": _rate(sum(r.both_ok for r in records), n),
        "priority": _rate(sum(r.priority_ok for r in records), n),
        "needs_reply": _rate(sum(r.needs_reply_ok for r in records), n),
        "injection_n": sum(r.is_injection for r in records),
    }


def monotonic(by_level: Mapping[str, Mapping[str, Any]], key: str = "both") -> bool | None:
    """True bila akurasi `key` tidak naik dari tinggi → sedang → rendah.

    Level dengan n=0 dilewati. None bila kurang dari dua level berisi (tidak bisa dinilai).
    """
    rates = [by_level[lv][key] for lv in CONFIDENCE_LEVELS
             if by_level.get(lv, {}).get("n")]
    if len(rates) < 2:
        return None
    return all(a >= b for a, b in zip(rates, rates[1:]))


def summarize(records: Iterable[Record]) -> dict[str, Any]:
    """Ringkasan satu putaran (atau gabungan beberapa putaran)."""
    records = list(records)
    classified = [r for r in records if r.classified]
    by_level = {lv: _bucket([r for r in classified if r.level == lv]) for lv in LEVEL_KEYS}
    return {
        "threads": len(records),
        "classified": len(classified),
        "failed": len(records) - len(classified),
        "confidence_missing": by_level[NO_LEVEL]["n"],
        "overall": _bucket(classified),
        "by_level": by_level,
        "monotonic_both": monotonic(by_level, "both"),
        "monotonic_category": monotonic(by_level, "category"),
        "monotonic_action": monotonic(by_level, "action"),
    }


def stability(runs: list[list[Record]]) -> dict[str, Any]:
    """Seberapa konsisten level dan label antarputaran untuk thread yang sama.

    Hanya thread yang berhasil diklasifikasi di semua putaran yang dihitung.
    """
    if len(runs) < 2:
        return {"runs": len(runs), "threads": None, "same_level": None, "same_labels": None,
                "per_thread": {}}
    by_id: dict[str, list[Record]] = {}
    for run in runs:
        for r in run:
            by_id.setdefault(r.thread_id, []).append(r)
    complete = {tid: rs for tid, rs in by_id.items()
                if len(rs) == len(runs) and all(r.classified for r in rs)}
    same_level = sum(len({r.level for r in rs}) == 1 for rs in complete.values())
    same_labels = sum(len({tuple(sorted((r.predicted or {}).items())) for r in rs}) == 1
                      for rs in complete.values())
    n = len(complete)
    return {
        "runs": len(runs),
        "threads": n,
        "same_level": _rate(same_level, n),
        "same_labels": _rate(same_labels, n),
        "per_thread": {tid: [r.level for r in rs] for tid, rs in sorted(by_id.items())},
    }


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def render_table(summary: Mapping[str, Any]) -> str:
    """Tabel teks ringkas untuk terminal."""
    lines = [
        f"thread {summary['threads']}, terklasifikasi {summary['classified']}, "
        f"gagal {summary['failed']}, confidence kosong {summary['confidence_missing']}",
        "",
        f"{'level':<8} {'n':>3} {'kategori':>9} {'aksi':>6} {'keduanya':>9} "
        f"{'prioritas':>10} {'injeksi':>8}",
    ]
    rows = [*((lv, summary["by_level"][lv]) for lv in LEVEL_KEYS), ("semua", summary["overall"])]
    for name, b in rows:
        lines.append(
            f"{name:<8} {b['n']:>3} {_fmt(b['category']):>9} {_fmt(b['action']):>6} "
            f"{_fmt(b['both']):>9} {_fmt(b['priority']):>10} {b['injection_n']:>8}"
        )
    mono = {True: "ya", False: "TIDAK", None: "tidak bisa dinilai (<2 level berisi)"}
    lines += ["", f"urutan tinggi >= sedang >= rendah (keduanya): {mono[summary['monotonic_both']]}"]
    return "\n".join(lines)
