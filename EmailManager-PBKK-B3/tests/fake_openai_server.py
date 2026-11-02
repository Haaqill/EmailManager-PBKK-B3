"""Server OpenAI-compatible palsu untuk menguji smoke_test_llm.py tanpa API kampus.

Mode:
  tools_ok      model memanggil label_email dengan argumen valid; round-trip divalidasi ketat
  no_tools      model menjawab teks biasa, lalu JSON valid untuk permintaan tanpa tools
  reject_tools  HTTP 400 jika ada parameter tools; JSON valid tanpa tools
  bad_args      model memanggil tool dengan category di luar enum
  bad_json      tanpa tool calling dan JSON fallback rusak
  auto_rejected HTTP 400 untuk tool_choice "auto" (seperti vLLM tanpa auto tool choice),
                tool call valid untuk tool_choice bernama
  rt_rejected   tool call valid, tetapi pesan tool (round-trip) ditolak HTTP 400
  redirect      HTTP 307 ke alamat http lain
  disconnect    koneksi diputus tanpa respons
  list_json     respons JSON berupa list, bukan objek
  reject_all    HTTP 404 untuk semua permintaan (mis. LLM_MODEL salah)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOpenAI:
    def __init__(self, mode: str, api_key: str = "test-key-123456"):
        self.mode = mode
        self.api_key = api_key
        self.requests: list[dict] = []
        self.errors: list[str] = []
        self.auth_headers: list[str | None] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # diam
                pass

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(req)
                outer.auth_headers.append(self.headers.get("Authorization"))
                if outer.mode == "redirect":
                    self.send_response(307)
                    self.send_header("Location", "http://redirect-target.invalid/v1/chat/completions")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if outer.mode == "disconnect":
                    self.close_connection = True
                    self.connection.close()
                    return
                if outer.mode == "list_json":
                    body = b"[1, 2]"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path != "/v1/chat/completions":
                    return self._send(404, {"error": {"message": "not found"}})
                if self.headers.get("Authorization") != f"Bearer {outer.api_key}":
                    return self._send(401, {"error": {"message": "invalid api key"}})
                status, payload = outer.respond(req)
                self._send(status, payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @staticmethod
    def _completion(message: dict) -> dict:
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def _validate_round_trip(self, messages: list[dict]) -> str | None:
        """Tiru validasi ketat endpoint OpenAI untuk pesan tool."""
        pending: set[str] = set()
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("type") != "function":
                        return "tool_calls[].type harus 'function'"
                    if not isinstance(tc.get("function", {}).get("arguments"), str):
                        return "function.arguments harus string"
                    if not tc.get("id"):
                        return "tool_calls[].id wajib"
                    pending.add(tc["id"])
            elif m.get("role") == "tool":
                tcid = m.get("tool_call_id")
                if tcid not in pending:
                    return f"tool_call_id {tcid!r} tidak cocok dengan tool_calls sebelumnya"
                pending.discard(tcid)
        if pending:
            return "ada tool_calls tanpa pesan tool balasan"
        return None

    def respond(self, req: dict) -> tuple[int, dict]:
        messages = req.get("messages", [])
        has_tools = bool(req.get("tools"))
        has_tool_msg = any(m.get("role") == "tool" for m in messages)
        valid_json = '```json\n{"category": "akademik", "priority": "mendesak", "reason": "Jadwal UTS berubah."}\n```'

        if self.mode == "reject_tools" and has_tools:
            return 400, {"error": {"message": "'tools' is not supported for this model"}}
        if self.mode in ("no_tools", "reject_tools"):
            if has_tools:
                return 200, self._completion({"role": "assistant", "content": "Ini email akademik."})
            return 200, self._completion({"role": "assistant", "content": valid_json})
        if self.mode == "reject_all":
            return 404, {"error": {"message": "The model `salah` does not exist."}}
        if self.mode == "auto_rejected" and has_tools and req.get("tool_choice") == "auto":
            return 400, {"error": {"message": '"auto" tool choice requires --enable-auto-tool-choice'}}
        if self.mode == "rt_rejected" and has_tool_msg:
            return 400, {"error": {"message": "messages with role 'tool' are not supported"}}
        if self.mode == "bad_json":
            return 200, self._completion({"role": "assistant", "content": "kategori: akademik"})

        if has_tool_msg:
            err = self._validate_round_trip(messages)
            if err:
                self.errors.append(err)
                return 400, {"error": {"message": err}}
            return 200, self._completion({"role": "assistant", "content": "Label sudah diterapkan."})

        category = "penting" if self.mode == "bad_args" else "akademik"
        args = json.dumps({"category": category, "priority": "mendesak",
                           "reason": "Pemberitahuan perubahan jadwal UTS."})
        return 200, self._completion({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_abc123", "type": "function",
                            "function": {"name": "label_email", "arguments": args}}],
        })
