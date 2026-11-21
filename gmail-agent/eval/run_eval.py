"""Evaluasi klasifikasi per tingkat confidence pada eval/dataset.json.

Hanya tahap klasifikasi: thread diambil dari MockGmailAPIClient (dataset, bukan Gmail asli),
diredaksi lewat fetch_thread seperti di produksi, lalu diklasifikasi oleh node `classify`
milik InboxGraph. Tidak ada draf, tidak ada aksi Gmail.

Keluaran hanya label (kategori, prioritas, aksi, needs_reply, confidence) dan ID thread.
Isi email, summary, reason, dan pesan error LLM tidak dicetak maupun disimpan.

Pemakaian (dari folder gmail-agent/):

    python -m eval.run_eval                       # backend mock (DatasetLLM), tanpa jaringan
    python -m eval.run_eval --backend campus --runs 3 --out hasil.json

`--backend campus` mengirim isi dataset (fiktif) ke endpoint LLM_BASE_URL di .env.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Sequence

from app.agent.dispatcher import dispatch
from app.agent.graph import InboxGraph
from app.contracts import LLMClient, LLMUnavailableError
from app.gmail.mock_client import MockGmailAPIClient, load_dataset
from app.privacy.redact import release_pii_map
from eval.metrics import Record, compare, render_table, stability, summarize

DEFAULT_DATASET = "eval/dataset.json"


def run_once(llm: LLMClient, dataset_path: str, batch_id: str,
             ids: Sequence[str] | None = None) -> list[Record]:
    """Satu putaran klasifikasi atas semua thread dataset (atau `ids`)."""
    rows = [r for r in load_dataset(dataset_path) if not ids or r.id in ids]
    graph = InboxGraph(llm, MockGmailAPIClient(dataset_path))
    # Tidak lewat scan_emails: filter scan (unread/inbox) tidak boleh mengurangi sampel.
    ctx = graph._ctx(batch_id, {"fetch_thread"})
    threads, failed_fetch = [], set()
    try:
        for row in rows:
            res = dispatch("fetch_thread", {"thread_id": row.id}, ctx)
            if res.ok:
                threads.append(res.data.thread.model_dump(by_alias=True))
            else:
                failed_fetch.add(row.id)
        out = graph._classify({"threads": threads, "errors": []})
    finally:
        release_pii_map(batch_id)

    predicted = {c["thread_id"]: c for c in out["classifications"]}
    return [
        compare(row.id, predicted.get(row.id), row.expected.model_dump(),
                is_injection=row.is_injection)
        for row in rows
    ]


def make_eval_llm(backend: str, dataset_path: str) -> LLMClient:
    if backend == "mock":
        from app.llm.mock import DatasetLLM

        return DatasetLLM(dataset_path)
    from app.config import load_config
    from app.llm.campus import CampusLLM

    os.environ["LLM_BACKEND"] = "campus"   # hanya proses ini; .env tidak diubah
    return CampusLLM(load_config())


def evaluate(llm: LLMClient, dataset_path: str, runs: int,
             ids: Sequence[str] | None = None) -> dict[str, Any]:
    all_runs = [run_once(llm, dataset_path, f"eval-{i + 1}", ids) for i in range(runs)]
    return {
        "dataset": dataset_path,
        "runs": runs,
        "per_run": [summarize(r) for r in all_runs],
        "combined": summarize([rec for run in all_runs for rec in run]),
        "stability": stability(all_runs),
        "records": [[rec.to_dict() for rec in run] for run in all_runs],
    }


def _model_name(llm: LLMClient) -> str:
    cfg = getattr(llm, "_config", None)
    return getattr(cfg, "llm_model", None) or type(llm).__name__


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--backend", choices=["mock", "campus"], default="mock",
                   help="mock = DatasetLLM tanpa jaringan (bawaan); campus = endpoint di .env")
    p.add_argument("--runs", type=int, default=1, help="jumlah putaran (stabilitas level)")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--ids", nargs="*", help="batasi ke thread tertentu, mis. t001 t006")
    p.add_argument("--out", help="simpan hasil lengkap (label saja) sebagai JSON")
    args = p.parse_args(argv)
    if args.runs < 1:
        p.error("--runs minimal 1")

    logging.basicConfig(level=logging.ERROR)
    llm = make_eval_llm(args.backend, args.dataset)
    try:
        result = evaluate(llm, args.dataset, args.runs, args.ids)
    except LLMUnavailableError:
        print("LLM tidak tersedia; evaluasi dihentikan.", file=sys.stderr)
        return 1
    result["backend"] = args.backend
    result["model"] = _model_name(llm)

    print(f"backend {args.backend}, model {result['model']}, putaran {args.runs}\n")
    if args.runs > 1:
        for i, s in enumerate(result["per_run"], 1):
            print(f"--- putaran {i} ---\n{render_table(s)}\n")
        print("--- gabungan semua putaran ---")
    print(render_table(result["combined"]))
    st = result["stability"]
    if st["threads"] is not None:
        print(f"\nstabilitas ({st['threads']} thread): level sama {st['same_level'] * 100:.0f}%, "
              f"label sama {st['same_labels'] * 100:.0f}%")
    if args.backend == "mock":
        print("\nCatatan: level mock berasal dari crc32 thread_id, bukan kualitas klasifikasi.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nhasil lengkap: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
