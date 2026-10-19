"""Baca dan validasi .env. Gagal cepat dengan pesan jelas.

Dua pintu masuk:
- load_config() / get_config(): konfigurasi lengkap untuk aplikasi (6 variabel LLM_*).
- load_endpoint_config(): hanya endpoint (URL, key, model) untuk smoke_test_llm.py,
  karena LLM_API_STYLE dan LLM_TOOL_MODE justru ditentukan dari hasil smoke test.
"""
from __future__ import annotations
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from dotenv import dotenv_values, load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


class ConfigError(ValueError):
    """Konfigurasi tidak lengkap atau tidak valid."""

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
        raise ConfigError(f"{name} kosong di .env. Lihat .env.example.")
    return v

def _choice(name: str, allowed: set[str]) -> str:
    v = _require(name)
    if v not in allowed:
        raise ConfigError(f"{name}={v!r} tidak dikenal. Pilihan: {sorted(allowed)}")
    return v

def load_config() -> Config:
    backend = _choice("LLM_BACKEND", {"mock", "campus"})
    api_style = _choice("LLM_API_STYLE", {"openai", "ollama"})
    tool_mode = _choice("LLM_TOOL_MODE", {"native", "json"})

    eval_path = os.getenv("EVAL_DATASET_PATH", "eval/dataset.json").strip() or (
        "eval/dataset.json"
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


# ---------- konfigurasi endpoint (smoke test, transport HTTP) ----------

_ENDPOINT_KEYS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


def _mask(secret: str) -> str:
    if not secret:
        return "<kosong>"
    if len(secret) <= 8:
        return "****"
    return f"{secret[:3]}…{secret[-2:]} ({len(secret)} karakter)"


@dataclass(frozen=True)
class LLMConfig:
    """Endpoint LLM saja. API key tidak pernah ikut tercetak (repr dimasking)."""

    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout_s: float = 60.0
    # Embedding (Fase 4) opsional; kosong berarti belum tersedia.
    embedding_model: str | None = None

    @property
    def chat_completions_url(self) -> str:
        """URL endpoint OpenAI-compatible.

        LLM_BASE_URL boleh diisi `https://host/v1` (gaya SDK OpenAI) atau
        langsung URL lengkap yang berakhir `/chat/completions`.
        """
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @property
    def masked_key(self) -> str:
        return _mask(self.api_key)

    def describe(self) -> str:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or self.base_url
        safe_url = self.base_url
        if parsed.username or parsed.password:   # jangan cetak user:password@ di URL
            safe_url = parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]).geturl()
        lines = [
            f"Base URL : {safe_url} (host: {host})",
            f"Endpoint : {self.chat_completions_url}",
            f"Model    : {self.model}",
            f"API key  : {self.masked_key}",
            f"Timeout  : {self.timeout_s:g} detik",
            f"Embedding: {self.embedding_model or '(belum diatur)'}",
        ]
        return "\n".join(lines)


def load_endpoint_config(env_file: str | os.PathLike | None = DEFAULT_ENV_FILE,
                         environ: dict[str, str] | None = None) -> LLMConfig:
    """Muat endpoint LLM. Variabel environment menimpa nilai dari file .env."""
    file_values = {k: v or "" for k, v in dotenv_values(env_file).items()} if env_file else {}
    env = os.environ if environ is None else environ
    merged = {**file_values, **{k: v for k, v in env.items() if k.startswith("LLM_")}}

    missing = [k for k in _ENDPOINT_KEYS if not merged.get(k, "").strip()]
    if missing:
        raise ConfigError(
            "Konfigurasi LLM belum lengkap. Isi di .env (salin dari .env.example): "
            + ", ".join(missing)
        )

    base_url = merged["LLM_BASE_URL"].strip()
    parsed = urlparse(base_url)
    if "@" in parsed.netloc:
        raise ConfigError("LLM_BASE_URL tidak boleh berisi user:password@; taruh kredensial di LLM_API_KEY.")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"LLM_BASE_URL bukan URL http(s) yang valid: {base_url!r}")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise ConfigError(
            "LLM_BASE_URL memakai http tanpa enkripsi ke host non-lokal. "
            "Gunakan https agar API key dan isi email tidak terkirim polos."
        )

    timeout_raw = merged.get("LLM_TIMEOUT_S", "").strip() or "60"
    try:
        timeout_s = float(timeout_raw)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError
    except ValueError:
        raise ConfigError(f"LLM_TIMEOUT_S harus angka positif, bukan {timeout_raw!r}") from None

    api_key = merged["LLM_API_KEY"].strip()
    if any(ord(c) < 32 or ord(c) > 126 for c in api_key):
        raise ConfigError("LLM_API_KEY berisi spasi tersembunyi, baris baru, atau karakter non-ASCII; "
                          "salin ulang key-nya.")

    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=merged["LLM_MODEL"].strip(),
        timeout_s=timeout_s,
        embedding_model=merged.get("LLM_EMBEDDING_MODEL", "").strip() or None,
    )


if __name__ == "__main__":
    try:
        print(load_endpoint_config().describe())
    except ConfigError as exc:
        raise SystemExit(f"[config] {exc}")
