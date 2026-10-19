"""Workflow LangGraph batch (A).

fetch → classify → draft → build_plan → [berhenti] → review → execute → summarize

- LLM tidak memanggil tool Gmail; semua tool lewat dispatcher dari node.
- Graph berhenti sebelum `review` (interrupt_before; langgraph 0.2.45 belum
  punya interrupt()/Command). UI membaca plan, lalu resume(decisions).
- State hanya berisi data teredaksi; PiiMap diambil lewat pii_map_for(batch_id)
  dan dibebaskan di report.
- Fatal (FatalToolError, LLMUnavailableError) diteruskan ke pemanggil.
"""
from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.agent.dispatcher import dispatch
from app.agent.prompts import (
    SUBMIT_CLASSIFICATION_TOOL,
    SUBMIT_DRAFT_TOOL,
    SYSTEM_CLASSIFY,
    SYSTEM_DRAFT,
    ClassificationOutput,
    DraftOutput,
    build_thread_message,
)
from app.agent.state import InboxState
from app.contracts import (
    ActionRecord,
    ErrorCode,
    LLMClient,
    LLMOutputError,
    PlanItem,
    ReviewDecision,
    ToolContext,
)
from app.gmail.tools import register_all_tools
from app.privacy.redact import pii_map_for, release_pii_map

READ_TOOLS = {"scan_emails", "fetch_thread"}
WRITE_TOOLS = {"label_thread", "archive_thread", "create_draft_reply"}
MAX_BATCH = 10
MAX_CORRECTIONS = 2


class InboxGraph:
    """Workflow satu batch. Satu batch = satu thread_id checkpointer (batch_id)."""

    def __init__(self, llm: LLMClient, gmail_client: Any, *, checkpointer: Any = None) -> None:
        self.llm = llm
        self.gmail_client = gmail_client
        register_all_tools()

        g = StateGraph(InboxState)
        # Nama node tidak boleh sama dengan key state (plan, report).
        for name, fn in (("fetch", self._fetch), ("classify", self._classify),
                         ("draft", self._draft), ("build_plan", self._plan),
                         ("review", self._review), ("execute", self._execute),
                         ("summarize", self._report)):
            g.add_node(name, fn)
        g.add_edge(START, "fetch")
        g.add_edge("fetch", "classify")
        g.add_edge("classify", "draft")
        g.add_edge("draft", "build_plan")
        g.add_edge("build_plan", "review")
        g.add_edge("review", "execute")
        g.add_edge("execute", "summarize")
        g.add_edge("summarize", END)
        self.graph = g.compile(
            checkpointer=checkpointer or MemorySaver(), interrupt_before=["review"]
        )

    # ------------------------------------------------------------ API untuk UI
    def start(self, batch_id: str, batch_size: int = MAX_BATCH) -> list[PlanItem]:
        """Jalankan sampai berhenti di review. Kembalikan plan (teks teredaksi)."""
        size = max(1, min(batch_size, MAX_BATCH))
        self.graph.invoke(
            {"batch_id": batch_id, "batch_size": size, "errors": [], "action_history": []},
            self._config(batch_id),
        )
        return self.get_plan(batch_id)

    def get_plan(self, batch_id: str) -> list[PlanItem]:
        values = self.graph.get_state(self._config(batch_id)).values
        return [PlanItem(**p) for p in values.get("plan", [])]

    def get_errors(self, batch_id: str) -> list[dict]:
        return list(self.graph.get_state(self._config(batch_id)).values.get("errors", []))

    def resume(self, batch_id: str, decisions: list[ReviewDecision]) -> dict:
        """Lanjutkan dari review dengan keputusan pengguna. Kembalikan report."""
        config = self._config(batch_id)
        self.graph.update_state(config, {"decisions": [d.model_dump() for d in decisions]})
        final = self.graph.invoke(None, config)
        return final["report"]

    @staticmethod
    def _config(batch_id: str) -> dict:
        return {"configurable": {"thread_id": batch_id}}

    def _ctx(self, batch_id: str, allowed: set[str]) -> ToolContext:
        return ToolContext(
            batch_id=batch_id,
            pii_map=pii_map_for(batch_id),
            allowed_tools=set(allowed),
            gmail_client=self.gmail_client,
        )

    # ------------------------------------------------------------ node
    def _fetch(self, state: InboxState) -> dict:
        ctx = self._ctx(state["batch_id"], READ_TOOLS)
        errors = list(state.get("errors", []))
        scan = dispatch("scan_emails", {"max_results": state["batch_size"]}, ctx)
        if not scan.ok:
            errors.append(_err("", "fetch", scan.message))
            return {"threads": [], "errors": errors}

        threads = []
        for summary in scan.data.threads:
            res = dispatch("fetch_thread", {"thread_id": summary.thread_id}, ctx)
            if res.ok:
                threads.append(res.data.thread.model_dump(by_alias=True))
            else:
                errors.append(_err(summary.thread_id, "fetch", res.message))
        return {"threads": threads, "errors": errors}

    def _classify(self, state: InboxState) -> dict:
        errors = list(state.get("errors", []))
        results = []
        for thread in state.get("threads", []):
            out = self._ask(SYSTEM_CLASSIFY, thread, SUBMIT_CLASSIFICATION_TOOL,
                            ClassificationOutput, "classify", errors)
            if out is not None:
                results.append(out.model_dump())
        return {"classifications": results, "errors": errors}

    def _draft(self, state: InboxState) -> dict:
        errors = list(state.get("errors", []))
        by_id = {t["thread_id"]: t for t in state.get("threads", [])}
        drafts = {}
        for c in state.get("classifications", []):
            if not c["needs_reply"]:
                continue
            out = self._ask(SYSTEM_DRAFT, by_id[c["thread_id"]], SUBMIT_DRAFT_TOOL,
                            DraftOutput, "draft", errors)
            if out is not None:
                drafts[c["thread_id"]] = out.body
        return {"drafts": drafts, "errors": errors}

    def _plan(self, state: InboxState) -> dict:
        errors = list(state.get("errors", []))
        drafts = state.get("drafts", {})
        plan = []
        for c in state.get("classifications", []):
            body = drafts.get(c["thread_id"])
            item = {**c, "draft_body": body, "needs_reply": c["needs_reply"] and body is not None}
            try:
                plan.append(PlanItem(**item).model_dump())
            except PydanticValidationError as exc:
                errors.append(_err(c["thread_id"], "plan", _short(exc)))
        return {"plan": plan, "errors": errors}

    def _review(self, state: InboxState) -> dict:
        """Normalisasi keputusan: thread tanpa keputusan dianggap rejected."""
        errors = list(state.get("errors", []))
        plan_ids = [p["thread_id"] for p in state.get("plan", [])]
        given: dict[str, dict] = {}
        for raw in state.get("decisions") or []:
            try:
                d = ReviewDecision(**raw)
            except PydanticValidationError as exc:
                errors.append(_err(str(raw.get("thread_id", "")), "review", _short(exc)))
                continue
            if d.thread_id not in plan_ids:
                errors.append(_err(d.thread_id, "review", "thread_id tidak ada di plan"))
                continue
            given[d.thread_id] = d.model_dump()
        decisions = [
            given.get(tid, ReviewDecision(thread_id=tid, status="rejected").model_dump())
            for tid in plan_ids
        ]
        return {"decisions": decisions, "errors": errors}

    def _execute(self, state: InboxState) -> dict:
        ctx = self._ctx(state["batch_id"], WRITE_TOOLS)
        plan = {p["thread_id"]: p for p in state.get("plan", [])}
        history = list(state.get("action_history", []))

        def run(tid: str, tool: str, args: dict) -> None:
            res = dispatch(tool, {"thread_id": tid, **args}, ctx)
            history.append(ActionRecord(thread_id=tid, tool=tool, ok=res.ok,
                                        error_code=res.error_code).model_dump())

        for d in state.get("decisions", []):
            if d["status"] == "rejected":
                continue
            item = d["edited"] if d["status"] == "edited" else plan[d["thread_id"]]
            tid = d["thread_id"]
            run(tid, "label_thread", {"category": item["category"], "priority": item["priority"],
                                      "reason": item["reason"]})
            if item["action"] == "archive":
                run(tid, "archive_thread", {})
            elif item["action"] == "trash":   # setelah MVP: butuh konfirmasi per item
                history.append(ActionRecord(thread_id=tid, tool="trash_thread", ok=False,
                                            error_code=ErrorCode.NOT_ALLOWED).model_dump())
            if item.get("draft_body"):
                run(tid, "create_draft_reply", {"body": item["draft_body"]})
        return {"action_history": history}

    def _report(self, state: InboxState) -> dict:
        decisions = state.get("decisions", [])
        history = state.get("action_history", [])
        per_tool: dict[str, dict[str, int]] = {}
        for rec in history:
            stat = per_tool.setdefault(rec["tool"], {"ok": 0, "gagal": 0})
            stat["ok" if rec["ok"] else "gagal"] += 1
        report = {
            "batch_id": state["batch_id"],
            "threads": len(state.get("threads", [])),
            "planned": len(state.get("plan", [])),
            "approved": sum(d["status"] in ("approved", "edited") for d in decisions),
            "rejected": sum(d["status"] == "rejected" for d in decisions),
            "actions_ok": sum(r["ok"] for r in history),
            "actions_failed": sum(not r["ok"] for r in history),
            "per_tool": per_tool,
            "failed": [r for r in history if not r["ok"]],
            "errors": list(state.get("errors", [])),
        }
        release_pii_map(state["batch_id"])
        return {"report": report}

    # ------------------------------------------------------------ LLM
    def _ask(self, system: str, thread: dict, tool: dict, model: type[BaseModel],
             stage: str, errors: list[dict]) -> BaseModel | None:
        """Satu keluaran tool tervalidasi Pydantic, dengan koreksi maks 2 kali.

        thread_id dipaksa sama dengan thread yang diproses. LLMOutputError dan
        validasi yang tetap gagal dicatat di errors; thread dilewati.
        """
        tid = thread["thread_id"]
        name = tool["function"]["name"]
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": build_thread_message(thread)}]
        for attempt in range(MAX_CORRECTIONS + 1):
            try:
                resp = self.llm.call_llm(messages, tools=[tool])
            except LLMOutputError as exc:
                errors.append(_err(tid, stage, str(exc)))
                return None
            call = next((c for c in resp.tool_calls if c.name == name), None)
            if call is None:
                problem = f"tool {name} tidak dipanggil"
                messages += [{"role": "assistant", "content": resp.content or ""},
                             {"role": "user", "content": f"{problem}. Panggil {name}."}]
            else:
                try:
                    return model(**{**call.arguments, "thread_id": tid})
                except PydanticValidationError as exc:
                    problem = _short(exc)
                    messages += [
                        {"role": "assistant", "content": resp.content, "tool_calls": [{
                            "id": call.id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(call.arguments)},
                        }]},
                        {"role": "tool", "tool_call_id": call.id,
                         "content": f"Argumen tidak valid: {problem}. Perbaiki dan panggil {name} lagi."},
                    ]
        errors.append(_err(tid, stage, f"keluaran tetap tidak valid setelah {MAX_CORRECTIONS} koreksi: {problem}"))
        return None


def _err(thread_id: str, stage: str, message: str | None) -> dict:
    return {"thread_id": thread_id, "stage": stage, "message": message or ""}


def _short(exc: PydanticValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())[:300]
