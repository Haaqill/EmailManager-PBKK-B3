"""Baca dan validasi .env. Gagal cepat dengan pesan jelas."""
from __future__ import annotations
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

Backend = Literal["mock", "campus"]
ApiStyle = Literal["openai", "ollama"]
ToolMode = Literal["native", "json"]

@dataclass(frozen=True)
class Config:
    llm_backend: Backend
    llm_api_style: ApiStyle
    llm_tool_mode: ToolMode
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    eval_dataset_path: str

def _require(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise ValueError(f"{name} kosong di .env. Lihat .env.example.")
    return v

def _choice(name: str, allowed: set[str]) -> str:
    v = _require(name)
    if v not in allowed:
        raise ValueError(f"{name}={v!r} tidak dikenal. Pilihan: {sorted(allowed)}")
    return v

def load_config() -> Config:
    backend = _choice("LLM_BACKEND", {"mock", "campus"})
    api_style = _choice("LLM_API_STYLE", {"openai", "ollama"})
    tool_mode = _choice("LLM_TOOL_MODE", {"native", "json"})

    eval_path = os.getenv("EVAL_DATASET_PATH", "eval/dataset.jsonl").strip() or (
        "eval/dataset.jsonl"
    )

    if backend == "campus":
        return Config(
            llm_backend=backend,
            llm_api_style=api_style,
            llm_tool_mode=tool_mode,
            llm_base_url=_require("LLM_BASE_URL"),
            llm_api_key=_require("LLM_API_KEY"),
            llm_model=_require("LLM_MODEL"),
            eval_dataset_path=eval_path,
        )
    
    # backend=mock: URL/key/model boleh kosong
    return Config(
        llm_backend=backend,
        llm_api_style=api_style,
        llm_tool_mode=tool_mode,
        llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "mock").strip() or "mock",
        eval_dataset_path=eval_path,
    )

@lru_cache(maxsize=1)
def get_config() -> Config:
    """Versi cached dari load_config().

    Dipakai oleh modul yang butuh config berulang (mis. client).
    Di tes, panggil get_config.cache_clear() sebelum monkeypatch env.
    """
    return load_config()
