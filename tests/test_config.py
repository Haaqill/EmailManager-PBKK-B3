# tests/test_config.py
import os
import pytest
from app.config import load_config

def test_config_mock_ok(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "mock")
    monkeypatch.setenv("LLM_API_STYLE", "openai")
    monkeypatch.setenv("LLM_TOOL_MODE", "json")
    cfg = load_config()
    assert cfg.llm_backend == "mock"

def test_config_backend_tidak_dikenal(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    with pytest.raises(ValueError, match="tidak dikenal"):
        load_config()

def test_config_campus_wajib_url(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "campus")
    monkeypatch.setenv("LLM_API_STYLE", "openai")
    monkeypatch.setenv("LLM_TOOL_MODE", "json")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        load_config()