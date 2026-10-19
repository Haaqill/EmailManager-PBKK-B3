"""Tes load_endpoint_config (dipakai smoke_test_llm.py)."""
from __future__ import annotations

import pytest

from app.config import ConfigError, load_endpoint_config

BASE = {
    "LLM_BASE_URL": "https://api.kampus.ac.id/v1",
    "LLM_API_KEY": "sk-rahasia-panjang-123",
    "LLM_MODEL": "model-uji",
}


def _load(**overrides: str):
    return load_endpoint_config(env_file=None, environ={**BASE, **overrides})


def test_valid_dan_url_chat_completions():
    cfg = _load()
    assert cfg.chat_completions_url == "https://api.kampus.ac.id/v1/chat/completions"
    assert _load(LLM_BASE_URL="https://h/v1/chat/completions").chat_completions_url == (
        "https://h/v1/chat/completions"
    )


def test_api_key_tidak_tercetak():
    cfg = _load()
    assert BASE["LLM_API_KEY"] not in repr(cfg)
    assert BASE["LLM_API_KEY"] not in cfg.describe()


def test_tidak_butuh_api_style_dan_tool_mode():
    """Smoke test harus bisa jalan sebelum LLM_API_STYLE/LLM_TOOL_MODE ditentukan."""
    assert _load().model == "model-uji"


@pytest.mark.parametrize("key", ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"])
def test_variabel_kosong_ditolak(key):
    with pytest.raises(ConfigError, match=key):
        _load(**{key: ""})


@pytest.mark.parametrize(
    "url",
    ["http://api.kampus.ac.id/v1", "ftp://api.kampus.ac.id", "https://user:pw@api.kampus.ac.id"],
)
def test_url_tidak_aman_ditolak(url):
    with pytest.raises(ConfigError):
        _load(LLM_BASE_URL=url)


def test_http_lokal_diizinkan():
    assert _load(LLM_BASE_URL="http://localhost:11434/v1").base_url.startswith("http://")


@pytest.mark.parametrize("timeout", ["0", "-5", "abc", "inf"])
def test_timeout_tidak_valid_ditolak(timeout):
    with pytest.raises(ConfigError, match="LLM_TIMEOUT_S"):
        _load(LLM_TIMEOUT_S=timeout)


def test_api_key_dengan_baris_baru_ditolak():
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        _load(LLM_API_KEY="sk-abc\ndef")
