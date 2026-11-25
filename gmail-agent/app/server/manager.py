"""Koordinasi batch, runtime graph, dan pekerjaan latar belakang."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent.graph import InboxGraph
from app.config import ConfigError
from app.contracts import (
    LLMUnavailableError,
    PlanItem as InboxPlanItem,
    ReviewDecision,
)
from app.gmail.auth import ReauthRequired, auth_status
from app.gmail.factory import GmailConfigError, gmail_backend
from app.privacy.contract import PlanSnapshot, RawThreadMeta, build_plan_snapshot
from app.privacy.redact import pii_map_for, redact, release_pii_map
from app.server.errors import AgentError
from app.server.schemas import ExecuteBatchRequest, ExecuteDecision

logger = logging.getLogger("agent.server.manager")

_PRE_EXECUTION_STATES = (
    "queued",
    "scanning",
    "classifying",
    "drafting",
    "awaiting_review",
)


class BatchCancelled(Exception):
    """Batch dibatalkan atau kehilangan transisi status yang diharapkan."""


class InlineExecutor(Executor):
    """Executor sinkron untuk tes endpoint tanpa thread latar belakang."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future:
        future: Future = Future()
        if future.set_running_or_notify_cancel():
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)
        return future

    def shutdown(
        self, wait: bool = True, *, cancel_futures: bool = False
    ) -> None:
        del wait, cancel_futures
        return None


@dataclass
class _BatchRuntime:
    cancel: threading.Event = field(default_factory=threading.Event)
    graph: InboxGraph | None = None
    plan_snapshot: PlanSnapshot | None = None
    item_to_thread: dict[str, str] = field(default_factory=dict)
    thread_to_item: dict[str, str] = field(default_factory=dict)
    plan_by_item: dict[str, InboxPlanItem] = field(default_factory=dict)


class BatchManager:
    """Mengelola batch; isi email dan snapshot hanya tinggal di memori."""

    def __init__(
        self,
        registry: Any,
        llm_factory: Callable[..., Any],
        gmail_factory: Callable[..., Any],
        executor: Executor | None = None,
    ) -> None:
        self.registry = registry
        self.llm_factory = llm_factory
        self.gmail_factory = gmail_factory
        self.executor = (
            executor if executor is not None else ThreadPoolExecutor(max_workers=2)
        )
        self._runtimes: dict[str, _BatchRuntime] = {}
        self._lock = threading.RLock()

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)

    def start_batch(self, user_id: str, max_results: int) -> dict[str, str]:
        backend = self._gmail_backend()
        if backend == "gmail":
            try:
                status = auth_status(user_id)
            except ReauthRequired:
                raise AgentError(
                    503, "gmail_unavailable", "Gmail tidak tersedia."
                ) from None
            if status != "connected":
                raise AgentError(
                    409, "gmail_not_connected", "Gmail belum terhubung."
                )

        try:
            llm = self.llm_factory()
        except (ConfigError, LLMUnavailableError):
            raise AgentError(
                503, "llm_unavailable", "Layanan LLM tidak tersedia."
            ) from None

        batch_id = self.registry.create_batch(user_id, max_results)
        runtime = _BatchRuntime()
        with self._lock:
            self._runtimes[batch_id] = runtime
        try:
            self.executor.submit(
                self._run_start, batch_id, user_id, max_results, llm, runtime
            )
        except Exception as exc:
            self._log_failure(batch_id, exc)
            self._fail(batch_id, ("queued",))
            self._discard(batch_id)
            raise
        return {"batch_id": batch_id, "status": "queued"}

    def get_batch(self, batch_id: str, user_id: str) -> dict[str, Any]:
        record = self._require_owned(batch_id, user_id)
        status = record["status"]
        plan = None
        report = None
        with self._lock:
            runtime = self._runtimes.get(batch_id)
            if status == "awaiting_review" and runtime is not None:
                if runtime.plan_snapshot is not None:
                    plan = runtime.plan_snapshot.model_dump(mode="json")

        if status == "done" or (
            status == "failed" and self.registry.was_executing(batch_id)
        ):
            report = self.registry.build_report(batch_id)

        return {
            "batch_id": batch_id,
            "status": status,
            "filters": {"max_results": record["max_results"]},
            "plan": plan,
            "report": report,
        }

    def execute(
        self, batch_id: str, user_id: str, request: ExecuteBatchRequest
    ) -> dict[str, str]:
        record = self._require_owned(batch_id, user_id)
        item_actions = self.registry.get_item_actions(batch_id)
        decisions_by_item: dict[str, Any] = {}
        for decision in request.decisions:
            if decision.item_id not in item_actions:
                raise AgentError(422, "invalid_request", "Permintaan tidak valid.")
            if decision.item_id in decisions_by_item:
                raise AgentError(422, "invalid_request", "Permintaan tidak valid.")
            if "edited_draft_body" in decision.model_fields_set and (
                decision.decision != "approve"
                or item_actions[decision.item_id] != "draft_reply"
            ):
                raise AgentError(422, "invalid_request", "Permintaan tidak valid.")
            decisions_by_item[decision.item_id] = decision

        if record["status"] in {"executing", "done"}:
            return {"status": "executing"}
        if record["status"] != "awaiting_review":
            raise AgentError(409, "invalid_state", "Status batch tidak valid.")
        if request.plan_version != record["plan_version"]:
            raise AgentError(
                409, "plan_version_mismatch", "Versi rencana sudah berubah."
            )

        with self._lock:
            runtime = self._runtimes.get(batch_id)
        if runtime is None or runtime.graph is None:
            raise AgentError(409, "invalid_state", "Status batch tidak valid.")

        if not self.registry.transition(batch_id, ["awaiting_review"], "executing"):
            current = self.registry.get(batch_id, user_id)
            if current is not None and current["status"] in {"executing", "done"}:
                return {"status": "executing"}
            raise AgentError(409, "invalid_state", "Status batch tidak valid.")

        try:
            self.registry.save_decisions(
                batch_id,
                {
                    item_id: decision.decision
                    for item_id, decision in decisions_by_item.items()
                },
            )
            self.executor.submit(
                self._run_execute,
                batch_id,
                runtime,
                list(decisions_by_item.values()),
            )
        except Exception as exc:
            self._log_failure(batch_id, exc)
            self._fail(batch_id, ("executing",))
            self._discard(batch_id)
            raise
        return {"status": "executing"}

    def cancel(self, batch_id: str, user_id: str) -> dict[str, str]:
        record = self._require_owned(batch_id, user_id)
        if record["status"] == "cancelled":
            with self._lock:
                runtime = self._runtimes.get(batch_id)
                if runtime is not None:
                    runtime.cancel.set()
            self._discard(batch_id)
            return {"status": "cancelled"}
        if record["status"] not in _PRE_EXECUTION_STATES:
            raise AgentError(409, "invalid_state", "Status batch tidak valid.")
        if not self.registry.transition(
            batch_id, _PRE_EXECUTION_STATES, "cancelled"
        ):
            current = self.registry.get(batch_id, user_id)
            if current is not None and current["status"] == "cancelled":
                return {"status": "cancelled"}
            raise AgentError(409, "invalid_state", "Status batch tidak valid.")

        with self._lock:
            runtime = self._runtimes.get(batch_id)
            if runtime is not None:
                runtime.cancel.set()
        self._discard(batch_id)
        return {"status": "cancelled"}

    def require_owned(self, batch_id: str, user_id: str) -> dict[str, Any]:
        return self._require_owned(batch_id, user_id)

    def _require_owned(self, batch_id: str, user_id: str) -> dict[str, Any]:
        record = self.registry.get(batch_id, user_id)
        if record is None:
            raise AgentError(404, "batch_not_found", "Batch tidak ditemukan.")
        return record

    @staticmethod
    def _gmail_backend() -> str:
        try:
            backend = gmail_backend()
        except GmailConfigError:
            raise AgentError(
                503, "gmail_unavailable", "Gmail tidak tersedia."
            ) from None
        if backend not in {"mock", "gmail"}:
            raise AgentError(503, "gmail_unavailable", "Gmail tidak tersedia.")
        return backend

    def _run_start(
        self,
        batch_id: str,
        user_id: str,
        max_results: int,
        llm: Any,
        runtime: _BatchRuntime,
    ) -> None:
        try:
            gmail_client = self.gmail_factory(user_id=user_id)
            previous_stage = {"scanning": "queued", "classifying": "scanning",
                              "drafting": "classifying"}

            def on_stage(stage: str) -> None:
                if runtime.cancel.is_set():
                    raise BatchCancelled
                if not self.registry.transition(
                    batch_id, [previous_stage[stage]], stage
                ):
                    raise BatchCancelled

            def on_item_result(thread_id: str, result: dict[str, Any]) -> None:
                item_id = runtime.thread_to_item[thread_id]
                self.registry.record_item_result(
                    batch_id,
                    item_id,
                    result["status"],
                    result["labels"],
                    result["archived"],
                    result["draft_id"],
                    result["actions_ok"],
                    result["actions_failed"],
                )

            graph = InboxGraph(
                llm,
                gmail_client,
                on_stage=on_stage,
                on_item_result=on_item_result,
            )
            runtime.graph = graph
            plan = graph.start(batch_id, max_results)
            self._ensure_not_cancelled(runtime)

            raw_threads = {}
            for item in plan:
                self._ensure_not_cancelled(runtime)
                thread = gmail_client.get_thread(
                    thread_id=item.thread_id, max_messages=5
                )
                raw_threads[item.thread_id] = RawThreadMeta.model_validate(
                    {
                        "thread_id": item.thread_id,
                        "subject": thread.subject,
                        "from": thread.messages[0].from_,
                        "date": thread.messages[-1].date,
                        "attachments": thread.attachments,
                        "reply_to": thread.reply_to,
                    }
                )

            snapshot = build_plan_snapshot(
                [item.model_dump() for item in plan],
                raw_threads,
                pii_map_for(batch_id),
                plan_version=1,
            )
            self._ensure_not_cancelled(runtime)
            by_thread = {item.thread_id: item for item in plan}
            runtime.plan_snapshot = snapshot
            runtime.item_to_thread = {
                item.item_id: item.thread_id for item in snapshot.items
            }
            runtime.thread_to_item = {
                item.thread_id: item.item_id for item in snapshot.items
            }
            runtime.plan_by_item = {
                item.item_id: by_thread[item.thread_id] for item in snapshot.items
            }
            self.registry.set_plan(
                batch_id,
                [item.item_id for item in snapshot.items],
                1,
                item_actions={
                    item.item_id: item.action for item in snapshot.items
                },
            )
            self._ensure_not_cancelled(runtime)
            if not self.registry.transition(
                batch_id, ["drafting"], "awaiting_review"
            ):
                raise BatchCancelled
        except BatchCancelled:
            self._discard(batch_id)
        except Exception as exc:
            self._log_failure(batch_id, exc)
            self._fail(batch_id, ("queued", "scanning", "classifying", "drafting"))
            self._discard(batch_id)

    def _run_execute(
        self,
        batch_id: str,
        runtime: _BatchRuntime,
        decisions: list[ExecuteDecision],
    ) -> None:
        try:
            graph = runtime.graph
            if graph is None:
                raise RuntimeError("Graph batch tidak tersedia.")
            pii_map = pii_map_for(batch_id)
            internal_decisions: list[ReviewDecision] = []
            for decision in decisions:
                thread_id = runtime.item_to_thread[decision.item_id]
                plan_item = runtime.plan_by_item[decision.item_id]
                if decision.decision == "reject":
                    internal_decisions.append(
                        ReviewDecision(thread_id=thread_id, status="rejected")
                    )
                    continue
                plan_snapshot = runtime.plan_snapshot
                if plan_snapshot is None:
                    raise RuntimeError("Snapshot batch tidak tersedia.")
                snapshot_item = next(
                    item
                    for item in plan_snapshot.items
                    if item.item_id == decision.item_id
                )
                if (
                    snapshot_item.requires_confirmation
                    and not decision.confirmed_trash
                ):
                    continue
                if decision.edited_draft_body is not None:
                    edited = plan_item.model_copy(
                        update={
                            "draft_body": redact(
                                decision.edited_draft_body, pii_map
                            ),
                            "needs_reply": True,
                        }
                    )
                    edited = InboxPlanItem.model_validate(edited.model_dump())
                    internal_decisions.append(
                        ReviewDecision(
                            thread_id=thread_id,
                            status="edited",
                            edited=edited,
                        )
                    )
                else:
                    internal_decisions.append(
                        ReviewDecision(thread_id=thread_id, status="approved")
                    )

            graph.resume(batch_id, internal_decisions)
            if not self.registry.transition(batch_id, ["executing"], "done"):
                self._discard(batch_id)
                return
            self._discard(batch_id)
        except Exception as exc:
            self._log_failure(batch_id, exc)
            self._fail(batch_id, ("executing",))
            self._discard(batch_id)

    @staticmethod
    def _ensure_not_cancelled(runtime: _BatchRuntime) -> None:
        if runtime.cancel.is_set():
            raise BatchCancelled

    def _fail(self, batch_id: str, from_statuses: tuple[str, ...]) -> None:
        try:
            self.registry.transition(batch_id, from_statuses, "failed")
        except Exception as exc:
            self._log_failure(batch_id, exc)

    @staticmethod
    def _log_failure(batch_id: str, exc: Exception) -> None:
        logger.warning("Batch %s gagal (%s).", batch_id, type(exc).__name__)

    def _discard(self, batch_id: str) -> None:
        release_pii_map(batch_id)
        with self._lock:
            self._runtimes.pop(batch_id, None)
