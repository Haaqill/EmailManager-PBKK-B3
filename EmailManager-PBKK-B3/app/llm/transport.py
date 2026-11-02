"""Transport HTTP mentah ke LLM kampus: `send_chat_request()`.

Dipakai smoke_test_llm.py, dan bisa dipakai CampusLLM sebagai lapisan bawah.
Sengaja tidak bernama `call_llm` agar tidak tertukar dengan LLMClient.call_llm
(kontrak 1), yang mengembalikan LLMResponse.

Hanya memakai pustaka standar, jadi tidak bergantung pada SDK tertentu.
Jika ternyata API kampus tidak OpenAI-compatible, cukup ubah fungsi ini
(dan `extract_message`) tanpa menyentuh bagian lain.

Keamanan:
- Redirect ditolak, agar header Authorization (API key) tidak ikut terkirim ke
  alamat lain, termasuk turun dari https ke http.
- Untuk host lokal (127.0.0.1/localhost) proxy dari environment dilewati.
"""
from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from app.config import LOOPBACK_HOSTS, LLMConfig


logger = logging.getLogger("gmail_agent.llm.transport")
logger.setLevel(logging.INFO)


class LLMHTTPError(RuntimeError):
    def __init__(self, status: int | None, message: str, retry_after: str | None = None,
                 timed_out: bool = False):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.message = message
        self.retry_after = retry_after   # nilai header Retry-After apa adanya (detik atau tanggal HTTP)
        # Klien menyerah, tetapi server mungkin MASIH memproses permintaan ini.
        self.timed_out = timed_out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise LLMHTTPError(code, f"Endpoint mengalihkan ke {urlparse(newurl).netloc or newurl}; "
                                 "redirect ditolak agar API key tidak ikut terkirim. "
                                 "Perbaiki LLM_BASE_URL.")


def _opener(url: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
    if urlparse(url).hostname in LOOPBACK_HOSTS:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    """Return tool names only; never log tool schemas or message content."""
    names: list[str] = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names


def _forced_tool_name(tool_choice: Any) -> str | None:
    if not isinstance(tool_choice, dict):
        return None
    function = tool_choice.get("function")
    name = function.get("name") if isinstance(function, dict) else None
    return name if isinstance(name, str) else None


def _gateway_error_kind(detail: str) -> str:
    """Classify an HTTP error without logging the provider's raw response."""
    lowered = detail.lower()
    if "tool_choice" in lowered:
        return "tool_choice_unsupported"
    if "tools" in lowered and ("not supported" in lowered or "unsupported" in lowered):
        return "tools_unsupported"
    if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return "model_not_found"
    if "api key" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "authentication_failed"
    if "rate limit" in lowered:
        return "rate_limited"
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return "text_error"
    return "json_error" if isinstance(payload, dict) else "non_object_error"


def _response_metadata(response: dict[str, Any]) -> tuple[str | None, bool, list[str]]:
    """Extract safe response diagnostics without retaining content or arguments."""
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    calls = extract_tool_calls(message)
    names = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str):
            names.append(name)
    finish_reason = choice.get("finish_reason")
    return (finish_reason if isinstance(finish_reason, str) else None, bool(calls), names)


def send_chat_request(cfg: LLMConfig, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None,
             **extra: Any) -> tuple[dict[str, Any], float]:
    """Kirim satu permintaan chat completions. Mengembalikan (json_respons, detik)."""
    payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
    if tools:
        payload["tools"] = tools
    payload.update({k: v for k, v in extra.items() if v is not None})

    url = cfg.chat_completions_url
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
    )
    started = time.perf_counter()
    try:
        with _opener(url).open(req, timeout=cfg.timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except LLMHTTPError:
        raise
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        error_kind = _gateway_error_kind(detail)
        logger.warning(
            "llm HTTP error metadata",
            extra={
                "gateway_host": urlparse(url).netloc,
                "http_status": exc.code,
                "gateway_error_kind": error_kind,
            },
        )
        raise LLMHTTPError(exc.code, f"gateway_error={error_kind}", retry_after) from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise LLMHTTPError(None, f"Timeout setelah {cfg.timeout_s:g} detik", timed_out=True) from None
        raise LLMHTTPError(None, f"Tidak bisa menghubungi endpoint: {exc.reason}") from None
    except TimeoutError:
        raise LLMHTTPError(None, f"Timeout setelah {cfg.timeout_s:g} detik", timed_out=True) from None
    except (http.client.HTTPException, OSError) as exc:
        raise LLMHTTPError(None, f"Koneksi terputus: {type(exc).__name__}") from None
    elapsed = time.perf_counter() - started

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(
            "llm response metadata",
            extra={
                "gateway_host": urlparse(url).netloc,
                "response_format": "non_json",
            },
        )
        raise LLMHTTPError(None, "Respons gateway bukan JSON") from None
    if not isinstance(data, dict):
        logger.warning(
            "llm response metadata",
            extra={
                "gateway_host": urlparse(url).netloc,
                "response_format": "non_object_json",
            },
        )
        raise LLMHTTPError(None, "Respons JSON gateway bukan objek")
    finish_reason, has_tool_calls, tool_names = _response_metadata(data)
    logger.info(
        "llm response metadata",
        extra={
            "gateway_host": urlparse(url).netloc,
            "response_model": data.get("model") if isinstance(data.get("model"), str) else None,
            "finish_reason": finish_reason,
            "has_tool_calls": has_tool_calls,
            "response_tool_names": tool_names,
        },
    )
    return data, elapsed


def extract_message(response: dict[str, Any]) -> dict[str, Any]:
    """Ambil `choices[0].message` dari respons OpenAI-compatible."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        logger.warning("llm response metadata", extra={"response_format": "missing_choices"})
        raise LLMHTTPError(None, "Format respons gateway tidak memiliki choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        logger.warning("llm response metadata", extra={"response_format": "missing_message"})
        raise LLMHTTPError(None, "choices[0].message bukan objek")
    return message


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Read modern ``tool_calls`` and the legacy OpenAI ``function_call`` shape."""
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        return [c for c in calls if isinstance(c, dict)]
    legacy = message.get("function_call")
    if isinstance(legacy, dict):
        return [{
            "id": legacy.get("id") or "legacy_function_call",
            "type": "function",
            "function": legacy,
        }]
    return []
