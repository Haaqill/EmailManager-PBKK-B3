"""Baca dan validasi .env. Gagal cepat dengan pesan jelas."""
import os
from dataclasses import dataclass
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    llm_backend: Literal["mock", "campus"]
    llm_api_style: Literal["openai", "ollama"]
    llm_tool_mode: Literal["native", "json"]
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
    style = _choice("LLM_API_STYLE", {"openai", "ollama"})
    mode = _choice("LLM_TOOL_MODE", {"native", "json"})

    if backend == "campus":
        return Config(
            llm_backend=backend,
            llm_api_style=style,
            llm_tool_mode=mode,
            llm_base_url=_require("LLM_BASE_URL"),
            llm_api_key=_require("LLM_API_KEY"),
            llm_model=_require("LLM_MODEL"),
            eval_dataset_path=os.getenv("EVAL_DATASET_PATH", "eval/dataset.jsonl"),
        )
    # backend=mock: URL/key/model boleh kosong
    return Config(
        llm_backend=backend,
        llm_api_style=style,
        llm_tool_mode=mode,
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "mock"),
        eval_dataset_path=os.getenv("EVAL_DATASET_PATH", "eval/dataset.jsonl"),
    )
