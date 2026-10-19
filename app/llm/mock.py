"""MockLLM — LLM palsu untuk tes (M1, A).

Desain:
- Antrean LLMResponse yang di-pop per panggilan. Tes menentukan urutan persis.
- Setiap panggilan mencatat messages & tools yang diterima, agar tes bisa
  memverifikasi bahwa workflow mengirim prompt yang benar.
- Jika antrean habis, raise AssertionError — mencegah tes "lulus" karena
  tidak sengaja tidak memanggil LLM.
- Bisa mensimulasikan error dengan mengantrekan exception:
  antrekan LLMUnavailableError atau LLMOutputError sebagai item.
- Tidak meniru koreksi/retry. Itu tanggung jawab CampusLLM.
- Deterministik: usage palsu berdasarkan panjang pesan, bukan acak.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts import LLMResponse, LLMUnavailableError, LLMOutputError, Usage


class MockLLM:
    """LLM palsu yang mengembalikan urutan LLMResponse yang ditentukan tes.

    Pemakaian dasar::

        llm = MockLLM([
            _respons_tool("submit_classification", {...}),
            _respons_tool("submit_draft", {...}),
        ])
        resp = llm.call_llm(messages=[...], tools=[...])
        assert resp.tool_calls[0].name == "submit_classification"

    Simulasi error::

        llm = MockLLM([LLMUnavailableError("server mati")])
        with pytest.raises(LLMUnavailableError):
            llm.call_llm(messages=[...])
    """

    def __init__(
        self,
        responses: list[LLMResponse | Exception] | None = None,
        *,
        default_model: str = "mock-llm",
    ) -> None:
        self._responses: list[LLMResponse | Exception] = list(responses or [])
        self.default_model = default_model

        # Rekaman untuk verifikasi di tes
        self.calls: list[dict] = []

    # ── API publik ──────────────────────────────────────────────

    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        """Ambil respons berikutnya dari antrean.

        Mencatat panggilan ke self.calls. Raise AssertionError jika
        antrean kosong, agar tes tidak "lulus" karena LLM tidak dipanggil.
        """
        self.calls.append(
            {
                "messages": _deepcopy_messages(messages),
                "tools": _deepcopy_messages(tools) if tools else None,
            }
        )

        if not self._responses:
            raise AssertionError(
                f"MockLLM kehabisan respons. Panggilan ke-{len(self.calls)} "
                f"tidak punya respons yang diantrekan. "
                f"Tambahkan LLMResponse ke konstruktor MockLLM."
            )

        item = self._responses.pop(0)

        # Simulasi error
        if isinstance(item, Exception):
            raise item

        return item

    # ── Utilitas untuk tes ──────────────────────────────────────

    @property
    def remaining(self) -> int:
        """Jumlah respons yang belum di-pop."""
        return len(self._responses)

    def push(self, *items: LLMResponse | Exception) -> None:
        """Tambahkan respons ke ujung antrean (untuk tes bertahap)."""
        self._responses.extend(items)

    def reset(self) -> None:
        """Kosongkan antrean dan rekaman panggilan."""
        self._responses.clear()
        self.calls.clear()


# ══════════════════════════════════════════════════════════════════
# Helper untuk membuat LLMResponse di tes
# ══════════════════════════════════════════════════════════════════


def _deepcopy_messages(value):
    """Copy dangkal list + dict agar tes tidak bisa memutasi rekaman."""
    if value is None:
        return None
    return [
        dict(m) if isinstance(m, dict) else m for m in value
    ]


def _usage(model: str, prompt_chars: int, completion_chars: int) -> Usage:
    """Usage palsu yang deterministik berdasarkan panjang teks.

    Prompt ~4 karakter per token, completion ~4 karakter per token.
    Bukan akurat, tapi cukup untuk tes yang memeriksa usage terisi.
    """
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, completion_chars // 4) if completion_chars else 0
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=0,  # mock tidak punya latensi nyata
        model=model,
        api_style="openai",
        tool_mode="json",
        retries=0,
    )


def _total_chars(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def make_text_response(
    content: str, *, model: str = "mock-llm", prompt_chars: int = 0
) -> LLMResponse:
    """LLMResponse berisi teks biasa (tanpa tool_calls).

    Dipakai untuk menguji jalur yang tidak memakai tool calling.
    """
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=_usage(model, prompt_chars, len(content)),
    )


def make_tool_response(
    tool_name: str,
    arguments: dict,
    *,
    tool_call_id: str | None = None,
    content: str | None = None,
    model: str = "mock-llm",
    prompt_chars: int = 0,
) -> LLMResponse:
    """LLMResponse berisi satu tool_call.

    Dipakai untuk submit_classification dan submit_draft.

    tool_call_id dibuat deterministik jika tidak diberikan, agar
    workflow yang memeriksa id bisa diuji.
    """
    from app.contracts import ToolCall

    if tool_call_id is None:
        tool_call_id = f"call_{tool_name}_1"

    return LLMResponse(
        content=content,
        tool_calls=[
            ToolCall(id=tool_call_id, name=tool_name, arguments=arguments)
        ],
        usage=_usage(model, prompt_chars, len(str(arguments))),
    )


def make_multi_tool_response(
    calls: list[tuple[str, dict]],
    *,
    ids: list[str] | None = None,
    content: str | None = None,
    model: str = "mock-llm",
    prompt_chars: int = 0,
) -> LLMResponse:
    """LLMResponse berisi beberapa tool_call sekaligus.

    Dipakai jika model kampus mendukung parallel tool calls.
    """
    from app.contracts import ToolCall

    if ids is None:
        ids = [f"call_{name}_{i}" for i, (name, _) in enumerate(calls)]

    if len(ids) != len(calls):
        raise ValueError("ids dan calls harus punya panjang sama")

    tool_calls = [
        ToolCall(id=ids[i], name=name, arguments=args)
        for i, (name, args) in enumerate(calls)
    ]
    size = sum(len(str(a)) for _, a in calls)
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        usage=_usage(model, prompt_chars, size),
    )

# ══════════════════════════════════════════════════════════════════
# DatasetLLM — LLM palsu untuk demo offline (LLM_BACKEND=mock)
# ══════════════════════════════════════════════════════════════════

_DRAFT_TEMPLATES = {
    "id": "Terima kasih atas emailnya. Saya sudah menerima pesan ini dan akan segera menindaklanjuti.",
    "en": "Thank you for your email. I have received it and will follow up shortly.",
}


class DatasetLLM:
    """Menjawab submit_classification / submit_draft dari `expected` di dataset.

    thread_id dibaca dari baris "thread_id: ..." pesan user (build_thread_message).
    Tidak ada jaringan; cocok untuk latihan demo dan tes end-to-end.
    """

    def __init__(self, dataset_path: str) -> None:
        from app.gmail.mock_client import load_dataset

        self.rows = {r.id: r for r in load_dataset(dataset_path)}
        self.calls: list[dict] = []

    def call_llm(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        import re

        self.calls.append({"messages": _deepcopy_messages(messages), "tools": tools})
        user = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
        match = re.search(r"^thread_id: (\S+)$", user, re.MULTILINE)
        subject = re.search(r"^Subjek: (.*)$", user, re.MULTILINE)
        tool = (tools or [{}])[0].get("function", {}).get("name")
        if not match or match.group(1) not in self.rows or tool is None:
            return make_text_response("Tidak ada data untuk thread ini.")
        row = self.rows[match.group(1)]
        prompt_chars = _total_chars(messages)

        if tool == "submit_draft":
            body = _DRAFT_TEMPLATES.get(row.lang, _DRAFT_TEMPLATES["id"])
            return make_tool_response(tool, {"thread_id": row.id, "body": body},
                                      model="dataset-llm", prompt_chars=prompt_chars)
        exp = row.expected
        return make_tool_response(tool, {
            "thread_id": row.id,
            "summary": subject.group(1) if subject else row.id,
            "category": exp.category, "priority": exp.priority, "action": exp.action,
            "needs_reply": exp.needs_reply, "reason": "jawaban mock dari dataset",
        }, model="dataset-llm", prompt_chars=prompt_chars)
