"""Tes untuk app/config.py.

Semua tes memakai monkeypatch.setenv/delenv untuk mengisolasi env.
load_dotenv() dipanggil saat import, tapi env yang di-monkeypatch
akan menang karena os.getenv membaca env proses lebih dulu.
"""
from __future__ import annotations

import pytest

from app.config import Config, get_config, load_config


# ── Fixture: env bersih untuk setiap tes ─────────────────────────────


@pytest.fixture(autouse=True)
def _bersihkan_cache():
    """Pastikan get_config() tidak memakai hasil cache tes sebelumnya."""
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _set_mock_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("LLM_API_STYLE", "openai")
    monkeypatch.setenv("LLM_TOOL_MODE", "json")


def _set_campus_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "campus")
    monkeypatch.setenv("LLM_API_STYLE", "openai")
    monkeypatch.setenv("LLM_TOOL_MODE", "native")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.kampus.ac.id/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
    monkeypatch.setenv("LLM_MODEL", "llama-3.1-70b")


# ── Skenario sukses ──────────────────────────────────────────────────


def test_mock_backend_berhasil_tanpa_url_key_model(monkeypatch):
    _set_mock_env(monkeypatch)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    cfg = load_config()

    assert isinstance(cfg, Config)
    assert cfg.llm_backend == "mock"
    assert cfg.llm_api_style == "openai"
    assert cfg.llm_tool_mode == "json"
    assert cfg.llm_base_url == ""
    assert cfg.llm_api_key == ""
    assert cfg.llm_model == "mock"  # default untuk mock


def test_campus_backend_berhasil_dengan_env_lengkap(monkeypatch):
    _set_campus_env(monkeypatch)

    cfg = load_config()

    assert cfg.llm_backend == "campus"
    assert cfg.llm_base_url == "https://api.kampus.ac.id/v1"
    assert cfg.llm_api_key == "sk-test-key"
    assert cfg.llm_model == "llama-3.1-70b"


def test_eval_path_default_jika_tidak_diisi(monkeypatch):
    _set_mock_env(monkeypatch)
    monkeypatch.delenv("EVAL_DATASET_PATH", raising=False)

    cfg = load_config()

    assert cfg.eval_dataset_path == "eval/dataset.json"


def test_eval_path_bisa_dioverride(monkeypatch):
    _set_mock_env(monkeypatch)
    monkeypatch.setenv("EVAL_DATASET_PATH", "tests/fixtures/dataset.json")

    cfg = load_config()

    assert cfg.eval_dataset_path == "tests/fixtures/dataset.json"


# ── Skenario gagal: nilai tidak dikenal ──────────────────────────────


@pytest.mark.parametrize("value", ["gemini", "openai-compatible", "", "MOCK"])
def test_backend_tidak_dikenal(monkeypatch, value):
    _set_mock_env(monkeypatch)
    monkeypatch.setenv("LLM_BACKEND", value)

    with pytest.raises(ValueError, match="LLM_BACKEND"):
        load_config()


@pytest.mark.parametrize("value", ["anthropic", "", "OpenAI"])
def test_api_style_tidak_dikenal(monkeypatch, value):
    _set_mock_env(monkeypatch)
    monkeypatch.setenv("LLM_API_STYLE", value)

    with pytest.raises(ValueError, match="LLM_API_STYLE"):
        load_config()


@pytest.mark.parametrize("value", ["react", "", "Native"])
def test_tool_mode_tidak_dikenal(monkeypatch, value):
    _set_mock_env(monkeypatch)
    monkeypatch.setenv("LLM_TOOL_MODE", value)

    with pytest.raises(ValueError, match="LLM_TOOL_MODE"):
        load_config()


# ── Skenario gagal: backend=campus tapi env wajib kosong ─────────────


def test_campus_tanpa_base_url_gagal(monkeypatch):
    _set_campus_env(monkeypatch)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        load_config()


def test_campus_tanpa_api_key_gagal(monkeypatch):
    _set_campus_env(monkeypatch)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_config()


def test_campus_tanpa_model_gagal(monkeypatch):
    _set_campus_env(monkeypatch)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(ValueError, match="LLM_MODEL"):
        load_config()


def test_campus_dengan_api_key_spasi_saja_gagal(monkeypatch):
    """Nilai '   ' harus dianggap kosong setelah .strip()."""
    _set_campus_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "   ")

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        load_config()


# ── Cache ────────────────────────────────────────────────────────────


def test_get_config_mengembalikan_objek_sama(monkeypatch):
    _set_mock_env(monkeypatch)

    a = get_config()
    b = get_config()

    assert a is b  # cached


def test_get_config_cache_clear_membaca_ulang(monkeypatch):
    _set_mock_env(monkeypatch)
    a = get_config()

    get_config.cache_clear()
    monkeypatch.setenv("LLM_API_STYLE", "ollama")
    b = get_config()

    assert a is not b
    assert a.llm_api_style == "openai"
    assert b.llm_api_style == "ollama"

def test_llm_timeout_default_dan_dari_env(monkeypatch):
    from app.config import ConfigError, load_config

    for k, v in {"LLM_BACKEND": "mock", "LLM_API_STYLE": "openai", "LLM_TOOL_MODE": "native"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    assert load_config().llm_timeout_s == 120.0
    monkeypatch.setenv("LLM_TIMEOUT_S", "180")
    assert load_config().llm_timeout_s == 180.0
    monkeypatch.setenv("LLM_TIMEOUT_S", "nol")
    with pytest.raises(ConfigError, match="LLM_TIMEOUT_S"):
        load_config()
