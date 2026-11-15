"""Aplikasi Streamlit: proses batch → tabel review → jalankan → laporan (D).

Jalankan dari root repo:  streamlit run app/ui/streamlit_app.py
LLM_BACKEND=mock → DatasetLLM (offline); campus → LLM kampus.
Gmail backend dipilih lewat GMAIL_BACKEND di environment/.env/Streamlit secrets.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:   # streamlit run hanya menambahkan folder skrip ke sys.path
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from app.agent.graph import MAX_BATCH, InboxGraph
from app.config import ConfigError, get_config
from app.contracts import Category, FatalToolError, LLMUnavailableError, Priority
from app.gmail.auth import OAuthConfigurationError, ReauthRequired, get_credentials
from app.gmail.factory import GmailConfigError, gmail_backend, make_gmail_client
from app.llm.client import make_llm
from app.privacy.redact import pii_map_for
from app.ui.review import plan_to_rows, report_lines, rows_to_decisions


def _new_graph(backend: str) -> InboxGraph:
    return InboxGraph(make_llm(), make_gmail_client(backend))


def _reset_batch() -> None:
    for key in ("batch_id", "plan", "report", "errors"):
        st.session_state.pop(key, None)


def main() -> None:
    st.set_page_config(page_title="Gmail Inbox Manager", layout="wide")
    st.title("Gmail Inbox Manager")

    try:
        cfg = get_config()
        backend = gmail_backend(st.secrets)
    except (ConfigError, GmailConfigError, OSError, ValueError) as exc:
        st.error(f"Konfigurasi belum siap: {exc}")
        return

    with st.sidebar:
        st.caption(f"LLM: **{cfg.llm_backend}** · Gmail: **{backend}**")
        if backend == "gmail" and st.button("Login Gmail / perbarui sesi"):
            try:
                get_credentials(interactive=True)
                st.session_state.pop("graph", None)
                st.success("Login berhasil. Token tersimpan di keyring lokal.")
                st.rerun()
            except OAuthConfigurationError as exc:
                st.error(f"Konfigurasi OAuth Gmail tidak cocok: {exc}")
            except (ReauthRequired, OSError, ValueError) as exc:
                st.error(f"Login Gmail gagal: {exc}")
            except Exception:
                st.error("Login Gmail gagal. Periksa credentials.json dan konfigurasi OAuth.")

    try:
        if ("graph" not in st.session_state
                or st.session_state.get("gmail_backend") != backend):
            if st.session_state.get("gmail_backend") != backend:
                _reset_batch()
            st.session_state.graph = _new_graph(backend)
            st.session_state.gmail_backend = backend
        graph = st.session_state.graph
        if backend == "gmail":
            graph.gmail_client.check_connection()
    except FatalToolError as exc:
        st.error(f"Gmail connection failed: {exc}. Gunakan tombol login di sidebar.")
        return
    except (OSError, ValueError) as exc:
        st.error(f"Konfigurasi belum siap: {exc}")
        return
    graph: InboxGraph = st.session_state.graph

    with st.sidebar:
        if backend == "mock":
            st.info("Mock Mode")
            st.caption(f"Dataset mock: {cfg.eval_dataset_path}")
        else:
            st.success("Gmail Connected")
        size = st.slider("Ukuran batch", 1, MAX_BATCH, MAX_BATCH)
        reset_label = "Reset inbox mock" if backend == "mock" else "Reset batch"
        if st.button(reset_label):
            st.session_state.graph = _new_graph(backend)
            st.session_state.gmail_backend = backend
            _reset_batch()
            st.rerun()
        st.caption("Agen tidak mengirim email dan tidak menghapus apa pun.")

    if st.button(f"Proses {size} email", type="primary"):
        _reset_batch()
        st.session_state.batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        try:
            with st.spinner("Membaca dan mengklasifikasi email..."):
                st.session_state.plan = graph.start(st.session_state.batch_id, size)
                st.session_state.errors = graph.get_errors(st.session_state.batch_id)
        except (LLMUnavailableError, FatalToolError) as exc:
            st.error(f"Batch berhenti: {exc}")
            _reset_batch()

    plan = st.session_state.get("plan")
    if plan is not None and "report" not in st.session_state:
        _review(graph, plan)

    if "report" in st.session_state:
        _show_report(st.session_state.report)


def _review(graph: InboxGraph, plan: list) -> None:
    batch_id = st.session_state.batch_id
    for err in st.session_state.get("errors", []):
        st.warning(f"{err['thread_id'] or 'batch'} ({err['stage']}): {err['message']}")
    if not plan:
        st.info("Tidak ada email untuk ditinjau.")
        return

    pii_map = pii_map_for(batch_id)
    st.subheader(f"Rencana ({len(plan)} thread): periksa, edit, lalu jalankan")
    st.caption("Baris yang tidak dicentang ditolak: tidak ada label, arsip, maupun draft.")
    table = st.data_editor(
        pd.DataFrame(plan_to_rows(plan, pii_map)),
        key=f"editor-{batch_id}",
        hide_index=True,
        use_container_width=True,
        disabled=["thread_id", "ringkasan", "alasan"],
        column_config={
            "setujui": st.column_config.CheckboxColumn("Setujui", width="small"),
            "kategori": st.column_config.SelectboxColumn("Kategori", options=list(get_args(Category)), required=True),
            "prioritas": st.column_config.SelectboxColumn("Prioritas", options=list(get_args(Priority)), required=True),
            "aksi": st.column_config.SelectboxColumn("Aksi", options=["keep", "archive"], required=True),
            "draft": st.column_config.TextColumn("Draft balasan", width="large"),
        },
    )
    col1, col2 = st.columns(2)
    approve_all = col1.button("Setujui semua & jalankan")
    run = col2.button("Jalankan yang dicentang")
    if not (approve_all or run):
        return

    rows = table.to_dict("records")
    if approve_all:
        for r in rows:
            r["setujui"] = True
    try:
        decisions = rows_to_decisions(rows, plan, pii_map)
    except ValueError as exc:
        st.error(f"Hasil edit tidak valid: {exc}")
        return
    try:
        with st.spinner("Menjalankan aksi yang disetujui..."):
            st.session_state.report = graph.resume(batch_id, decisions)
    except (LLMUnavailableError, FatalToolError) as exc:
        st.error(f"Batch berhenti: {exc}")
        return
    st.rerun()


def _show_report(report: dict) -> None:
    st.subheader("Laporan")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Disetujui", report["approved"])
    c2.metric("Ditolak", report["rejected"])
    c3.metric("Aksi berhasil", report["actions_ok"])
    c4.metric("Aksi gagal", report["actions_failed"])
    for line in report_lines(report):
        st.write(line)
    if report["failed"]:
        st.dataframe(pd.DataFrame(report["failed"]), hide_index=True)
    for err in report["errors"]:
        st.warning(f"{err['thread_id'] or 'batch'} ({err['stage']}): {err['message']}")


if __name__ == "__main__":
    main()
