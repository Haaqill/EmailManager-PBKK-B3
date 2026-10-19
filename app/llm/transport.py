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
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from app.config import LOOPBACK_HOSTS, LLMConfig


class LLMHTTPError(RuntimeError):
    def __init__(self, status: int | None, message: str, retry_after: str | None = None):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.message = message
        self.retry_after = retry_after   # nilai header Retry-After apa adanya (detik atau tanggal HTTP)


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
        raise LLMHTTPError(exc.code, detail, retry_after) from None
    except urllib.error.URLError as exc:
        raise LLMHTTPError(None, f"Tidak bisa menghubungi endpoint: {exc.reason}") from None
    except TimeoutError:
        raise LLMHTTPError(None, f"Timeout setelah {cfg.timeout_s:g} detik") from None
    except (http.client.HTTPException, OSError) as exc:
        raise LLMHTTPError(None, f"Koneksi terputus: {type(exc).__name__}") from None
    elapsed = time.perf_counter() - started

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise LLMHTTPError(None, f"Respons bukan JSON: {body[:200]!r}") from None
    if not isinstance(data, dict):
        raise LLMHTTPError(None, f"Respons JSON bukan objek: {body[:200]!r}")
    return data, elapsed


def extract_message(response: dict[str, Any]) -> dict[str, Any]:
    """Ambil `choices[0].message` dari respons OpenAI-compatible."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LLMHTTPError(None, f"Format respons tidak dikenal: {json.dumps(response)[:300]}")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LLMHTTPError(None, "choices[0].message bukan objek")
    return message


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """`tool_calls` sebagai list objek (kosong jika tidak ada atau formatnya salah)."""
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    return [c for c in calls if isinstance(c, dict)]
