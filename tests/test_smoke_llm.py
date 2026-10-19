"""Tes Fase 0: load_endpoint_config dan smoke_test_llm.py terhadap server palsu."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import smoke_test_llm
from app.config import ConfigError, load_endpoint_config
from tests.fake_openai_server import FakeOpenAI

KEY = "test-key-123456"


def write_env(dirpath: str, base_url: str, key: str = KEY, model: str = "kampus-model") -> Path:
    path = Path(dirpath) / ".env"
    path.write_text(
        "# komentar\n"
        f'LLM_BASE_URL="{base_url}"\n'
        f"export LLM_API_KEY={key}\n"
        f"LLM_MODEL={model}  # komentar di akhir\n",
        encoding="utf-8",
    )
    return path


class ConfigTests(unittest.TestCase):
    def test_reads_env_file_and_masks_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_endpoint_config(write_env(d, "https://llm.kampus.ac.id/v1", key="sk-rahasia-sekali-123"),
                                  environ={})
        self.assertEqual(cfg.model, "kampus-model")
        self.assertEqual(cfg.chat_completions_url, "https://llm.kampus.ac.id/v1/chat/completions")
        self.assertNotIn("rahasia", repr(cfg))
        self.assertNotIn("rahasia", cfg.describe())

    def test_environment_overrides_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_endpoint_config(write_env(d, "https://a.ac.id/v1"),
                                  environ={"LLM_MODEL": "model-lain"})
        self.assertEqual(cfg.model, "model-lain")

    def test_full_endpoint_url_is_kept(self):
        cfg = load_endpoint_config(None, environ={
            "LLM_BASE_URL": "https://x.ac.id/api/chat/completions/",
            "LLM_API_KEY": "k", "LLM_MODEL": "m"})
        self.assertEqual(cfg.chat_completions_url, "https://x.ac.id/api/chat/completions")

    def test_missing_keys_listed(self):
        with self.assertRaises(ConfigError) as ctx:
            load_endpoint_config(None, environ={"LLM_BASE_URL": "https://x.ac.id/v1"})
        self.assertIn("LLM_API_KEY", str(ctx.exception))
        self.assertIn("LLM_MODEL", str(ctx.exception))

    def test_rejects_plain_http_to_remote_host(self):
        with self.assertRaises(ConfigError):
            load_endpoint_config(None, environ={"LLM_BASE_URL": "http://llm.kampus.ac.id/v1",
                                           "LLM_API_KEY": "k", "LLM_MODEL": "m"})

    def test_rejects_bad_timeout(self):
        with self.assertRaises(ConfigError):
            load_endpoint_config(None, environ={"LLM_BASE_URL": "https://x.ac.id/v1", "LLM_API_KEY": "k",
                                           "LLM_MODEL": "m", "LLM_TIMEOUT_S": "abc"})


class ConfigHardeningTests(unittest.TestCase):
    def test_nan_and_inf_timeout_rejected(self):
        for bad in ("nan", "inf", "-1", "0"):
            with self.subTest(bad), self.assertRaises(ConfigError):
                load_endpoint_config(None, environ={"LLM_BASE_URL": "https://x.ac.id/v1", "LLM_API_KEY": "k",
                                               "LLM_MODEL": "m", "LLM_TIMEOUT_S": bad})

    def test_key_with_newline_or_non_ascii_rejected(self):
        for bad in ("abc\ndef", "abc\u200bdef", "kunci–rahasia"):
            with self.subTest(repr(bad)), self.assertRaises(ConfigError) as ctx:
                load_endpoint_config(None, environ={"LLM_BASE_URL": "https://x.ac.id/v1",
                                               "LLM_API_KEY": bad, "LLM_MODEL": "m"})
            self.assertNotIn(bad, str(ctx.exception))

    def test_userinfo_in_url_rejected_without_echo(self):
        with self.assertRaises(ConfigError) as ctx:
            load_endpoint_config(None, environ={"LLM_BASE_URL": "https://u:sekret@x.ac.id/v1",
                                           "LLM_API_KEY": "k", "LLM_MODEL": "m"})
        self.assertNotIn("sekret", str(ctx.exception))

    def test_env_parser_edge_cases(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_bytes(
                "\ufeffLLM_BASE_URL=\"https://x.ac.id/v1\" # komentar\r\n"
                "export\tLLM_API_KEY='a#b'\r\n"
                "LLM_MODEL=model-x\t# komentar\r\n".encode("utf-8"))
            cfg = load_endpoint_config(path, environ={})
        self.assertEqual((cfg.base_url, cfg.api_key, cfg.model), ("https://x.ac.id/v1", "a#b", "model-x"))


class SmokeTests(unittest.TestCase):
    def run_smoke(self, mode: str, extra_args: list[str] | None = None):
        with FakeOpenAI(mode, api_key=KEY) as fake, tempfile.TemporaryDirectory() as d:
            env = write_env(d, fake.base_url)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = smoke_test_llm.main(["--env-file", str(env), *(extra_args or [])])
            return code, out.getvalue(), fake

    def test_tool_calling_pass(self):
        code, out, fake = self.run_smoke("tools_ok")
        self.assertEqual(code, 0, out)
        self.assertIn("LOLOS", out)
        self.assertEqual(fake.errors, [])
        # Permintaan kedua harus membawa tool_calls lengkap dan tool_call_id.
        second = fake.requests[1]["messages"]
        self.assertEqual(second[-1]["tool_call_id"], "call_abc123")
        self.assertIsInstance(second[-2]["tool_calls"][0]["function"]["arguments"], str)
        self.assertNotIn(KEY, out)

    def test_invalid_args_fail(self):
        code, out, _ = self.run_smoke("bad_args")
        self.assertEqual(code, 1, out)
        self.assertIn("Argumen tidak valid", out)

    def test_no_tool_call_uses_json_fallback(self):
        code, out, _ = self.run_smoke("no_tools")
        self.assertEqual(code, 3, out)
        self.assertIn("Fallback JSON valid", out)

    def test_rejected_tools_parameter_uses_json_fallback(self):
        code, out, _ = self.run_smoke("reject_tools")
        self.assertEqual(code, 3, out)

    def test_broken_fallback_fails(self):
        code, out, _ = self.run_smoke("bad_json")
        self.assertEqual(code, 1, out)

    def test_wrong_key_reports_401_without_leaking_key(self):
        with FakeOpenAI("tools_ok", api_key="kunci-benar") as fake, tempfile.TemporaryDirectory() as d:
            env = write_env(d, fake.base_url, key="kunci-salah-999")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = smoke_test_llm.main(["--env-file", str(env)])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 401", out.getvalue())
        self.assertNotIn("kunci-salah-999", out.getvalue())

    def test_named_tool_choice_used_when_auto_rejected(self):
        code, out, fake = self.run_smoke("auto_rejected")
        self.assertEqual(code, 0, out)
        self.assertIn("tool_choice bernama", out)

    def test_round_trip_rejected_still_passes_gate_with_warning(self):
        code, out, _ = self.run_smoke("rt_rejected")
        self.assertEqual(code, 0, out)
        self.assertIn("PERINGATAN", out)

    def test_redirect_refused_and_key_not_resent(self):
        code, out, fake = self.run_smoke("redirect")
        self.assertEqual(code, 1, out)
        self.assertIn("redirect ditolak", out)
        self.assertEqual(len(fake.requests), 1)

    def test_disconnect_and_bad_json_shape_do_not_crash(self):
        for mode in ("disconnect", "list_json"):
            with self.subTest(mode):
                code, out, _ = self.run_smoke(mode)
                self.assertEqual(code, 1, out)
                self.assertIn("FAIL", out)

    def test_localhost_bypasses_env_proxy(self):
        saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")}
        try:
            for k in ("HTTP_PROXY", "http_proxy"):
                os.environ[k] = "http://127.0.0.1:9"     # proxy palsu yang tidak ada
            for k in ("NO_PROXY", "no_proxy"):
                os.environ.pop(k, None)
            code, out, _ = self.run_smoke("tools_ok")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(code, 0, out)

    def test_rejecting_everything_blames_endpoint_not_tools(self):
        code, out, _ = self.run_smoke("reject_all")
        self.assertEqual(code, 1, out)
        self.assertIn("Periksa LLM_MODEL", out)
        self.assertNotIn("Tool calling tidak tersedia. Fallback", out)

    def test_missing_config_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("LLM_MODEL=x\n")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = smoke_test_llm.main(["--env-file", str(env)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
