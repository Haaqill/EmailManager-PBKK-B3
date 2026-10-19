"""CampusLLM — LLMClient untuk gateway LLM kampus (kontrak 1, A).

- Endpoint OpenAI-compatible lewat app/llm/transport.py.
- Tool calling native saja: smoke test (19 Okt) membuktikan native berfungsi,
  jadi mode json dan adapter ollama tidak diperlukan.
- Server mati (jaringan, 429, 5xx): retry maks 3 dengan jitter, lalu
  LLMUnavailableError. Status 4xx lain langsung LLMUnavailableError.
- 429 (rate limit): jeda retry mengikuti header Retry-After atau "Limit resets at"
  di isi pesan gateway, dibatasi 1-60 detik; tanpa petunjuk, pakai jeda biasa.
- Output rusak (arguments bukan objek JSON, atau tidak ada tool_call padahal
  tools diberikan): dikoreksi maks 2 kali, lalu LLMOutputError.
- usage dijumlahkan dari semua percobaan dalam satu panggilan.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)
from tenacity.wait import wait_base

from app.config import Config, ConfigError, LLMConfig, get_config
from app.contracts import LLMOutputError, LLMResponse, LLMUnavailableError, ToolCall, Usage
from app.llm.transport import (
    LLMHTTPError,
    extract_message,
    extract_tool_calls,
    send_chat_request,
)


RATE_LIMIT_MAX_WAIT_S = 60.0
_RESETS_AT_RE = re.compile(r"Limit resets at: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")


def rate_limit_delay(exc: BaseException | None, now: datetime | None = None) -> float | None:
    """Detik yang perlu ditunggu untuk 429, dibatasi 1..60. None jika bukan 429/tanpa petunjuk.

    Urutan: header Retry-After (detik atau tanggal HTTP), lalu "Limit resets at: ... UTC"
    di isi pesan gateway LLM kampus.
    """
    if not isinstance(exc, LLMHTTPError) or exc.status != 429:
        return None
    now = now or datetime.now(timezone.utc)
    seconds = None
    if exc.retry_after:
        value = exc.retry_after.strip()
        if value.isdigit():
            seconds = float(value)
        else:
            try:
                seconds = (parsedate_to_datetime(value) - now).total_seconds()
            except (TypeError, ValueError):
                seconds = None
    if seconds is None:
        match = _RESETS_AT_RE.search(exc.message or "")
        if match:
            reset = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            seconds = (reset - now).total_seconds()
    if seconds is None:
        return None
    return min(max(seconds, 1.0), RATE_LIMIT_MAX_WAIT_S)


class _RateLimitAwareWait(wait_base):
    """Untuk 429 pakai rate_limit_delay; selain itu jeda biasa (fallback)."""

    def __init__(self, fallback: Any) -> None:
        self.fallback = fallback

    def __call__(self, retry_state) -> float:
        delay = rate_limit_delay(retry_state.outcome.exception())
        return delay if delay is not None else self.fallback(retry_state)


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, LLMHTTPError) and (
        exc.status is None or exc.status == 429 or exc.status >= 500
    )


class CampusLLM:
    """Implementasi LLMClient untuk endpoint kampus."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        send: Callable[..., tuple[dict[str, Any], float]] = send_chat_request,
        max_retries: int = 3,
        max_corrections: int = 2,
        wait: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        cfg = config or get_config()
        if cfg.llm_tool_mode != "native" or cfg.llm_api_style != "openai":
            raise ConfigError(
                "CampusLLM hanya mendukung LLM_API_STYLE=openai dan LLM_TOOL_MODE=native "
                "(hasil smoke test: tool calling native berfungsi)."
            )
        self._config = cfg
        self._endpoint = LLMConfig(
            base_url=cfg.llm_base_url, api_key=cfg.llm_api_key, model=cfg.llm_model
        )
        self._send = send
        self._max_retries = max_retries
        self._max_corrections = max_corrections
        self._wait = _RateLimitAwareWait(
            wait if wait is not None else wait_random_exponential(multiplier=1, max=20)
        )
        self._sleep = sleep

    # ------------------------------------------------------------------ API
    def call_llm(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        messages = list(messages)
        totals = {"prompt": None, "completion": None, "total": None, "latency_ms": 0, "retries": 0}
        model = self._config.llm_model

        for attempt in range(self._max_corrections + 1):
            data = self._post(messages, tools, totals)
            model = data.get("model") or model
            message = extract_message(data)
            try:
                response = self._parse(message, tools)
            except _BrokenOutput as exc:
                if attempt == self._max_corrections:
                    raise LLMOutputError(
                        f"Output LLM tetap rusak setelah {self._max_corrections} koreksi: {exc}"
                    ) from None
                totals["retries"] += 1
                messages += [
                    {"role": "assistant", "content": message.get("content") or ""},
                    {"role": "user", "content": f"Output sebelumnya tidak valid: {exc}. "
                                                "Ulangi dengan memanggil tool yang diminta "
                                                "dengan argumen objek JSON yang valid."},
                ]
                continue
            content, tool_calls = response
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                usage=Usage(
                    prompt_tokens=totals["prompt"],
                    completion_tokens=totals["completion"],
                    total_tokens=totals["total"],
                    latency_ms=totals["latency_ms"],
                    model=model,
                    api_style="openai",
                    tool_mode="native",
                    retries=totals["retries"],
                ),
            )
        raise AssertionError("tidak tercapai")  # pragma: no cover

    # ------------------------------------------------------------ internal
    def _post(self, messages: list[dict], tools: list[dict] | None, totals: dict) -> dict:
        """Satu permintaan dengan retry untuk server mati. Menjumlahkan usage."""
        attempts = 0
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(self._max_retries + 1),
                wait=self._wait,
                sleep=self._sleep,
                retry=retry_if_exception(_retryable),
                reraise=False,
            ):
                with attempt:
                    attempts += 1
                    started = time.perf_counter()
                    try:
                        data, _ = self._send(self._endpoint, messages, tools=tools)
                    finally:
                        totals["latency_ms"] += int((time.perf_counter() - started) * 1000)
        except RetryError as exc:
            last = exc.last_attempt.exception()
            raise LLMUnavailableError(
                f"LLM kampus tidak tersedia setelah {self._max_retries} retry: {last}"
            ) from None
        except LLMHTTPError as exc:
            raise LLMUnavailableError(f"LLM kampus menolak permintaan: {exc}") from None
        finally:
            totals["retries"] += max(0, attempts - 1)

        usage = data.get("usage") or {}
        for key, src in (("prompt", "prompt_tokens"), ("completion", "completion_tokens"),
                         ("total", "total_tokens")):
            value = usage.get(src)
            if isinstance(value, int):
                totals[key] = (totals[key] or 0) + value
        return data

    def _parse(self, message: dict, tools: list[dict] | None) -> tuple[str | None, list[ToolCall]]:
        calls: list[ToolCall] = []
        for i, raw in enumerate(extract_tool_calls(message), start=1):
            fn = raw.get("function") or {}
            name = fn.get("name")
            if not isinstance(name, str) or not name:
                raise _BrokenOutput("tool_call tanpa nama fungsi")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    raise _BrokenOutput(f"arguments {name} bukan JSON") from None
            if not isinstance(args, dict):
                raise _BrokenOutput(f"arguments {name} bukan objek JSON")
            calls.append(ToolCall(id=raw.get("id") or f"call_{i}", name=name, arguments=args))
        if tools and not calls:
            raise _BrokenOutput("tidak ada tool_call, padahal tool wajib dipanggil")
        return message.get("content"), calls


class _BrokenOutput(Exception):
    """Output LLM yang bisa dikoreksi."""
