from __future__ import annotations

import logging
from concurrent.futures import Executor, Future
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import InboxGraph
from app.contracts import LLMUnavailableError
from app.gmail import auth as gmail_auth
from app.gmail.mock_client import MockGmailAPIClient
from app.llm.mock import DatasetLLM
from app.privacy.contract import PlanSnapshot
from app.server import manager as manager_module
from app.server import routes as routes_module
from app.server.app import create_app
from app.server.manager import InlineExecutor
from app.server.registry import BatchRegistry
from app.server.settings import Settings

TOKEN = "server-test-token-" + "x" * 32
DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset.json"
CANARY = "Isi Rahasia Canary 4815162342"


class QueuedExecutor(Executor):
    def __init__(self) -> None:
        self.tasks: list[tuple[Future, object, tuple, dict]] = []
        self.shutdown_called = False

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        self.tasks.append((future, fn, args, kwargs))
        return future

    def run_next(self):
        future, fn, args, kwargs = self.tasks.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.shutdown_called = True


class GmailTerhitung(MockGmailAPIClient):
    def __init__(self) -> None:
        super().__init__(DATASET)
        self.label_calls = 0

    def apply_labels(self, **kwargs):
        self.label_calls += 1
        return super().apply_labels(**kwargs)


def _headers(user_id: str = "42") -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "X-User-Id": user_id}


def _buat_app(
    registry_path: Path,
    *,
    executor: Executor | None = None,
    llm_factory=None,
    gmail_factory=None,
):
    registry = BatchRegistry(registry_path)
    klien_gmail = []

    def buat_gmail(user_id: str):
        client = (
            gmail_factory(user_id)
            if gmail_factory is not None
            else MockGmailAPIClient(DATASET)
        )
        klien_gmail.append(client)
        return client

    app = create_app(
        settings=Settings(agent_token=TOKEN),
        registry=registry,
        llm_factory=(
            llm_factory
            if llm_factory is not None
            else lambda: DatasetLLM(str(DATASET))
        ),
        gmail_factory=buat_gmail,
        executor=executor if executor is not None else InlineExecutor(),
    )
    return app, registry, klien_gmail


@pytest.fixture(autouse=True)
def _gunakan_backend_mock(monkeypatch):
    monkeypatch.setenv("GMAIL_BACKEND", "mock")


def test_alur_batch_lengkap_dan_snapshot_valid(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "alur.sqlite")
    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 3}},
                headers=_headers(),
            )
            assert started.status_code == 202
            assert started.json()["status"] == "queued"
            batch_id = started.json()["batch_id"]

            pending = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            )
            assert pending.status_code == 200
            payload = pending.json()
            assert payload["status"] == "awaiting_review"
            assert payload["filters"] == {"max_results": 3}
            snapshot = PlanSnapshot.model_validate(payload["plan"])
            assert snapshot.plan_version == 1
            assert [item.item_id for item in snapshot.items] == [
                "i_01",
                "i_02",
                "i_03",
            ]

            executed = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {"item_id": "i_01", "decision": "approve"},
                        {"item_id": "i_02", "decision": "reject"},
                    ],
                },
                headers=_headers(),
            )
            assert executed.status_code == 202
            assert executed.json() == {"status": "executing"}

            done = client.get(f"/v1/batches/{batch_id}", headers=_headers())
            assert done.status_code == 200
            assert done.json()["status"] == "done"
            assert done.json()["plan"] is None
            assert [item["status"] for item in done.json()["report"]["results"]] == [
                "ok",
                "rejected",
                "skipped",
            ]
            assert done.json()["report"]["summary"] == {
                "approved": 1,
                "rejected": 1,
                "actions_ok": 1,
                "actions_failed": 0,
            }
    finally:
        registry.close()


def test_status_stage_diperbarui_berurutan(tmp_path, monkeypatch):
    app, registry, _ = _buat_app(tmp_path / "stage-order.sqlite")
    transitions = []
    transition_asli = registry.transition

    def catat_transisi(batch_id, from_statuses, to_status):
        if to_status in {"scanning", "classifying", "drafting", "awaiting_review"}:
            transitions.append(to_status)
        return transition_asli(batch_id, from_statuses, to_status)

    monkeypatch.setattr(registry, "transition", catat_transisi)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 2}},
                headers=_headers(),
            )
        assert response.status_code == 202
        assert transitions == [
            "scanning",
            "classifying",
            "drafting",
            "awaiting_review",
        ]
    finally:
        registry.close()


def test_filter_bawaan_sepuluh_dan_executor_diinjeksi(tmp_path):
    executor = QueuedExecutor()
    app, registry, _ = _buat_app(
        tmp_path / "defaults.sqlite", executor=executor
    )
    try:
        with TestClient(app) as client:
            started = client.post("/v1/batches", json={}, headers=_headers())
            batch_id = started.json()["batch_id"]
            status = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            )
            assert status.json()["filters"] == {"max_results": 10}
            assert status.json()["status"] == "queued"
            cancelled = client.post(
                f"/v1/batches/{batch_id}/cancel", headers=_headers()
            )
            assert cancelled.json() == {"status": "cancelled"}
        assert app.state.manager.executor is executor
        assert len(executor.tasks) == 1
        assert executor.shutdown_called
    finally:
        registry.close()


def test_executor_default_memiliki_dua_worker(tmp_path):
    registry = BatchRegistry(tmp_path / "executor-default.sqlite")
    app = create_app(
        Settings(agent_token=TOKEN),
        registry,
        lambda: DatasetLLM(str(DATASET)),
        lambda user_id: MockGmailAPIClient(DATASET),
    )
    try:
        assert app.state.manager.executor._max_workers == 2
        with TestClient(app):
            pass
    finally:
        registry.close()


def test_executor_latar_belakang_menyelesaikan_kedua_job(tmp_path):
    registry = BatchRegistry(tmp_path / "thread-pool.sqlite")
    app = create_app(
        Settings(agent_token=TOKEN),
        registry,
        lambda: DatasetLLM(str(DATASET)),
        lambda user_id: MockGmailAPIClient(DATASET),
    )

    def tunggu_status(client, batch_id, expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            )
            status = response.json()["status"]
            if status == expected:
                return response.json()
            if status == "failed":
                pytest.fail("Batch gagal saat memakai executor thread.")
            time.sleep(0.01)
        pytest.fail(f"Batch tidak mencapai status {expected}.")

    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 1}},
                headers=_headers(),
            )
            assert started.status_code == 202
            assert started.json()["status"] == "queued"
            batch_id = started.json()["batch_id"]
            tunggu_status(client, batch_id, "awaiting_review")

            executed = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [{"item_id": "i_01", "decision": "approve"}],
                },
                headers=_headers(),
            )
            assert executed.status_code == 202
            assert executed.json() == {"status": "executing"}
            done = tunggu_status(client, batch_id, "done")
            assert done["report"]["results"][0]["status"] == "ok"
    finally:
        registry.close()


def test_auth_endpoint_backend_mock_dan_gmail(tmp_path):
    database = tmp_path / "auth-endpoint.sqlite"
    app, registry, _ = _buat_app(database)
    try:
        with TestClient(app) as client:
            status = client.get("/v1/auth/status", headers=_headers())
            login = client.post("/v1/auth/login", headers=_headers())

        assert status.status_code == 200
        assert status.json() == {"status": "connected"}
        assert login.status_code == 200
        assert login.json() == {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?mock=1"
        }
    finally:
        registry.close()


def test_auth_gmail_meneruskan_status_dan_memetakan_galat_login(
    tmp_path, monkeypatch
):
    app, registry, _ = _buat_app(tmp_path / "auth-gmail.sqlite")
    monkeypatch.setattr(routes_module, "gmail_backend", lambda: "gmail")
    monkeypatch.setattr(routes_module, "auth_status", lambda user_id: "expired")
    try:
        with TestClient(app) as client:
            status = client.get("/v1/auth/status", headers=_headers())
            assert status.json() == {"status": "expired"}

            monkeypatch.setattr(
                routes_module,
                "begin_login",
                lambda user_id: (_ for _ in ()).throw(
                    gmail_auth.OAuthConfigurationError(CANARY)
                ),
            )
            login = client.post("/v1/auth/login", headers=_headers())

        assert login.status_code == 503
        assert login.json() == {
            "error": {
                "code": "gmail_unavailable",
                "message": "Gmail tidak tersedia.",
            }
        }
        assert CANARY not in login.text
    finally:
        registry.close()


def test_backend_gmail_tidak_terhubung_menghasilkan_409(tmp_path, monkeypatch):
    app, registry, _ = _buat_app(tmp_path / "not-connected.sqlite")
    monkeypatch.setattr(manager_module, "gmail_backend", lambda: "gmail")
    monkeypatch.setattr(manager_module, "auth_status", lambda user_id: "expired")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/batches", json={}, headers=_headers()
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "gmail_not_connected"
    finally:
        registry.close()


@pytest.mark.parametrize("max_results", [0, 11, True])
def test_filter_tidak_valid_menghasilkan_422(tmp_path, max_results):
    app, registry, _ = _buat_app(tmp_path / "invalid-filters.sqlite")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/batches",
                json={"filters": {"max_results": max_results}},
                headers=_headers(),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
    finally:
        registry.close()


def test_endpoint_menolak_token_tidak_valid(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "unauthorized.sqlite")
    try:
        with TestClient(app) as client:
            response = client.get("/v1/auth/status")
        assert response.status_code == 401
        assert response.json() == {
            "error": {
                "code": "unauthorized",
                "message": "Autentikasi diperlukan.",
            }
        }
    finally:
        registry.close()


def test_galat_llm_sinkron_menghasilkan_503_generik(tmp_path):
    app, registry, _ = _buat_app(
        tmp_path / "llm-unavailable.sqlite",
        llm_factory=lambda: (_ for _ in ()).throw(
            LLMUnavailableError(CANARY)
        ),
    )
    try:
        with TestClient(app) as client:
            response = client.post("/v1/batches", json={}, headers=_headers())
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "llm_unavailable",
                "message": "Layanan LLM tidak tersedia.",
            }
        }
        assert CANARY not in response.text
    finally:
        registry.close()


def test_tidak_dapat_menebak_keberadaan_batch_milik_user_lain(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "ownership.sqlite")
    try:
        with TestClient(app) as client:
            started = client.post("/v1/batches", json={}, headers=_headers())
            batch_id = started.json()["batch_id"]
            responses = [
                client.get(
                    f"/v1/batches/{batch_id}", headers=_headers("43")
                ),
                client.post(
                    f"/v1/batches/{batch_id}/execute",
                    json={"plan_version": 1, "decisions": []},
                    headers=_headers("43"),
                ),
                client.post(
                    f"/v1/batches/{batch_id}/cancel", headers=_headers("43")
                ),
                client.get(
                    "/v1/batches/b_tidak-ada", headers=_headers("42")
                ),
            ]
        bodies = [response.json() for response in responses]
        assert all(response.status_code == 404 for response in responses)
        assert all(body == bodies[0] for body in bodies)
        assert bodies[0] == {
            "error": {
                "code": "batch_not_found",
                "message": "Batch tidak ditemukan.",
            }
        }
    finally:
        registry.close()


def test_execute_memeriksa_plan_version_dan_status(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "execute-errors.sqlite")
    try:
        with TestClient(app) as client:
            started = client.post("/v1/batches", json={}, headers=_headers())
            batch_id = started.json()["batch_id"]
            mismatch = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={"plan_version": 2, "decisions": []},
                headers=_headers(),
            )
            assert mismatch.status_code == 409
            assert mismatch.json()["error"]["code"] == "plan_version_mismatch"
    finally:
        registry.close()

    app, registry, _ = _buat_app(
        tmp_path / "invalid-state.sqlite", executor=QueuedExecutor()
    )
    try:
        with TestClient(app) as client:
            started = client.post("/v1/batches", json={}, headers=_headers())
            batch_id = started.json()["batch_id"]
            invalid = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={"plan_version": 1, "decisions": []},
                headers=_headers(),
            )
        assert invalid.status_code == 409
        assert invalid.json()["error"]["code"] == "invalid_state"
    finally:
        registry.close()


def test_execute_rejects_duplicate_item_and_draft_edit_non_draft(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "invalid-decisions.sqlite")
    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 1}},
                headers=_headers(),
            )
            batch_id = started.json()["batch_id"]
            duplicate = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {"item_id": "i_01", "decision": "approve"},
                        {"item_id": "i_01", "decision": "reject"},
                    ],
                },
                headers=_headers(),
            )
            edited = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {
                            "item_id": "i_01",
                            "decision": "approve",
                            "edited_draft_body": CANARY,
                        }
                    ],
                },
                headers=_headers(),
            )
            edited_null = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {
                            "item_id": "i_01",
                            "decision": "reject",
                            "edited_draft_body": None,
                        }
                    ],
                },
                headers=_headers(),
            )
        assert duplicate.status_code == 422
        assert edited.status_code == 422
        assert edited_null.status_code == 422
        assert CANARY not in edited.text
    finally:
        registry.close()


def test_idempotensi_execute_saat_executing_dan_done(tmp_path):
    executor = QueuedExecutor()
    app, registry, gmail_clients = _buat_app(
        tmp_path / "idempotent.sqlite",
        executor=executor,
        gmail_factory=lambda user_id: GmailTerhitung(),
    )
    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 1}},
                headers=_headers(),
            )
            batch_id = started.json()["batch_id"]
            executor.run_next()
            body = {
                "plan_version": 1,
                "decisions": [{"item_id": "i_01", "decision": "approve"}],
            }

            first = client.post(
                f"/v1/batches/{batch_id}/execute",
                json=body,
                headers=_headers(),
            )
            second = client.post(
                f"/v1/batches/{batch_id}/execute",
                json=body,
                headers=_headers(),
            )
            assert first.status_code == second.status_code == 202
            assert first.json() == second.json() == {"status": "executing"}
            assert len(executor.tasks) == 1

            executor.run_next()
            third = client.post(
                f"/v1/batches/{batch_id}/execute",
                json=body,
                headers=_headers(),
            )

        assert third.status_code == 202
        assert third.json() == {"status": "executing"}
        assert gmail_clients[0].label_calls == 1
    finally:
        registry.close()


def test_cancel_di_semua_status_dan_idempoten(tmp_path):
    app, registry, _ = _buat_app(tmp_path / "cancel-states.sqlite")
    try:
        with TestClient(app) as client:
            for status in (
                "queued",
                "scanning",
                "classifying",
                "drafting",
                "awaiting_review",
            ):
                batch_id = registry.create_batch("42", 1)
                if status != "queued":
                    assert registry.transition(batch_id, ["queued"], status)
                response = client.post(
                    f"/v1/batches/{batch_id}/cancel", headers=_headers()
                )
                repeated = client.post(
                    f"/v1/batches/{batch_id}/cancel", headers=_headers()
                )
                assert response.status_code == repeated.status_code == 202
                assert response.json() == repeated.json() == {
                    "status": "cancelled"
                }

            for status in ("executing", "done", "failed"):
                batch_id = registry.create_batch("42", 1)
                assert registry.transition(batch_id, ["queued"], status)
                response = client.post(
                    f"/v1/batches/{batch_id}/cancel", headers=_headers()
                )
                assert response.status_code == 409
                assert response.json()["error"]["code"] == "invalid_state"
    finally:
        registry.close()


def test_cancel_saat_fetch_menghentikan_graph_dan_membuang_runtime(tmp_path):
    app = None
    registry = BatchRegistry(tmp_path / "cancel-mid.sqlite")

    class GmailBatalkanSaatScan(MockGmailAPIClient):
        def list_threads(self, **kwargs):
            hasil = super().list_threads(**kwargs)
            batch_id = next(iter(app.state.manager._runtimes))
            cancelled = app.state.manager.cancel(batch_id, "42")
            assert cancelled == {"status": "cancelled"}
            return hasil

    app = create_app(
        Settings(agent_token=TOKEN),
        registry,
        lambda: DatasetLLM(str(DATASET)),
        lambda user_id: GmailBatalkanSaatScan(DATASET),
        InlineExecutor(),
    )
    try:
        with TestClient(app) as client:
            response = client.post("/v1/batches", json={}, headers=_headers())
            batch_id = response.json()["batch_id"]
            status = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            )
        assert response.status_code == 202
        assert status.json()["status"] == "cancelled"
        assert status.json()["plan"] is None
        assert batch_id not in app.state.manager._runtimes
    finally:
        registry.close()


def test_galat_llm_latar_belakang_menjadi_failed_tanpa_membocorkan(tmp_path, caplog):
    app, registry, _ = _buat_app(
        tmp_path / "background-failure.sqlite",
        llm_factory=lambda: DatasetLLM(str(DATASET)),
    )

    class LLMGagal:
        def call_llm(self, messages, tools=None):
            raise LLMUnavailableError(CANARY)

    app.state.manager.llm_factory = lambda: LLMGagal()
    try:
        with TestClient(app) as client:
            with caplog.at_level(logging.WARNING):
                started = client.post("/v1/batches", json={}, headers=_headers())
                batch_id = started.json()["batch_id"]
                result = client.get(
                    f"/v1/batches/{batch_id}", headers=_headers()
                )
        assert started.status_code == 202
        assert result.json()["status"] == "failed"
        assert result.json()["report"] is None
        assert CANARY not in caplog.text
        assert TOKEN not in caplog.text
        assert "LLMUnavailableError" in caplog.text
        assert TOKEN.encode() not in registry.path.read_bytes()
        assert CANARY.encode() not in registry.path.read_bytes()
    finally:
        registry.close()


def test_hasil_pertama_tetap_tersimpan_jika_callback_item_kedua_gagal(
    tmp_path, monkeypatch
):
    app, registry, _ = _buat_app(tmp_path / "item-progress.sqlite")
    asli = registry.record_item_result
    panggilan = 0

    def gagal_kedua(*args, **kwargs):
        nonlocal panggilan
        panggilan += 1
        if panggilan == 2:
            raise RuntimeError(CANARY)
        return asli(*args, **kwargs)

    monkeypatch.setattr(registry, "record_item_result", gagal_kedua)
    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 3}},
                headers=_headers(),
            )
            batch_id = started.json()["batch_id"]
            failed = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {"item_id": f"i_{index:02d}", "decision": "approve"}
                        for index in (1, 2, 3)
                    ],
                },
                headers=_headers(),
            )
            report = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            )
        assert failed.status_code == 202
        assert report.json()["status"] == "failed"
        results = report.json()["report"]["results"]
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "skipped"
        assert results[2]["status"] == "skipped"
    finally:
        registry.close()


def test_restart_rekonsiliasi_review_dan_executing_ke_failed(tmp_path):
    database = tmp_path / "restart.sqlite"
    registry = BatchRegistry(database)
    awaiting = registry.create_batch("42", 1)
    registry.set_plan(awaiting, ["i_01"], 1, {"i_01": "label_only"})
    assert registry.transition(awaiting, ["queued"], "awaiting_review")

    executing = registry.create_batch("42", 2)
    registry.set_plan(
        executing,
        ["i_01", "i_02"],
        1,
        {"i_01": "label_only", "i_02": "draft_reply"},
    )
    registry.save_decisions(executing, {"i_01": "approve", "i_02": "approve"})
    assert registry.transition(executing, ["queued"], "executing")
    registry.record_item_result(
        executing, "i_01", "ok", ["Kategori/Tugas"], False, None, 1, 0
    )
    registry.close()

    restarted_app, restarted_registry, _ = _buat_app(database)
    try:
        with TestClient(restarted_app) as client:
            review_result = client.get(
                f"/v1/batches/{awaiting}", headers=_headers()
            )
            executing_result = client.get(
                f"/v1/batches/{executing}", headers=_headers()
            )
        assert review_result.json()["status"] == "failed"
        assert review_result.json()["plan"] is None
        assert review_result.json()["report"] is None
        assert executing_result.json()["status"] == "failed"
        assert executing_result.json()["report"]["results"][0]["status"] == "ok"
        assert executing_result.json()["report"]["results"][1]["status"] == "skipped"
    finally:
        restarted_registry.close()


def test_draft_edit_diredaksi_di_graph_dan_dipulihkan_di_gmail(
    tmp_path, monkeypatch
):
    gmail_clients = []

    def gmail_factory(user_id):
        client = MockGmailAPIClient(DATASET)
        gmail_clients.append(client)
        return client

    app, registry, _ = _buat_app(
        tmp_path / "draft-edit.sqlite", gmail_factory=gmail_factory
    )
    observed_drafts = []
    resume_original = InboxGraph.resume

    def resume_spy(graph, batch_id, decisions):
        observed_drafts.extend(
            decision.edited.draft_body
            for decision in decisions
            if decision.edited is not None
        )
        return resume_original(graph, batch_id, decisions)

    monkeypatch.setattr(InboxGraph, "resume", resume_spy)
    original_body = "Hubungi saya kembali di 0812-3456-7890."
    try:
        with TestClient(app) as client:
            started = client.post(
                "/v1/batches",
                json={"filters": {"max_results": 2}},
                headers=_headers(),
            )
            batch_id = started.json()["batch_id"]
            snapshot = client.get(
                f"/v1/batches/{batch_id}", headers=_headers()
            ).json()["plan"]
            draft_item = next(
                item for item in snapshot["items"] if item["action"] == "draft_reply"
            )
            response = client.post(
                f"/v1/batches/{batch_id}/execute",
                json={
                    "plan_version": 1,
                    "decisions": [
                        {
                            "item_id": draft_item["item_id"],
                            "decision": "approve",
                            "edited_draft_body": original_body,
                        }
                    ],
                },
                headers=_headers(),
            )
        assert response.status_code == 202
        assert observed_drafts
        assert original_body not in observed_drafts[0]
        assert "0812-3456-7890" not in observed_drafts[0]
        assert gmail_clients[0].drafts[0]["body"] == original_body
    finally:
        registry.close()
