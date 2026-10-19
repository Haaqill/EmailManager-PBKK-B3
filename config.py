"""Konfigurasi LLM kampus (Fase 0).

Membaca LLM_BASE_URL, LLM_API_KEY, dan LLM_MODEL dari environment atau file .env.
Tidak ada model yang di-hardcode. API key tidak pernah ikut tercetak (repr dimasking).

Pemakaian:
    from config import load_llm_config
    cfg = load_llm_config()          # baca .env di folder proyek
    cfg.chat_completions_url         # https://.../v1/chat/completions

Jalankan `python config.py` untuk mengecek konfigurasi tanpa memanggil API.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"

REQUIRED_KEYS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


class ConfigError(RuntimeError):
    """Konfigurasi tidak lengkap atau tidak valid."""


_EXPORT_RE = re.compile(r"^export\s+")


def _parse_value(value: str) -> str:
    """Nilai .env: `"..."` (escape \\" dan \\n diproses), `'...'` apa adanya, atau polos.
    Komentar ` #...` di belakang nilai diabaikan."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        out, i = [], 1
        while i < len(value):
            ch = value[i]
            if quote == '"' and ch == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                i += 2
                continue
            if ch == quote:
                return "".join(out)         # sisa baris (komentar) diabaikan
            out.append(ch)
            i += 1
        return value                         # kutip tidak ditutup: pakai apa adanya
    hash_pos = re.search(r"\s#", value)
    return value[:hash_pos.start()].rstrip() if hash_pos else value


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parser .env minimal (KEY=VALUE, komentar #, kutip, `export` opsional, BOM, CRLF).

    Dipakai agar proyek tidak wajib bergantung pada python-dotenv.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = _EXPORT_RE.sub("", raw.strip())
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = _parse_value(value)
    return values


def _mask(secret: str) -> str:
    if not secret:
        return "<kosong>"
    if len(secret) <= 8:
        return "****"
    return f"{secret[:3]}…{secret[-2:]} ({len(secret)} karakter)"


@dataclass(frozen=True)
class LLMConfig:
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


def load_llm_config(env_file: str | os.PathLike | None = DEFAULT_ENV_FILE,
                    environ: dict[str, str] | None = None) -> LLMConfig:
    """Muat konfigurasi. Variabel environment menimpa nilai dari file .env."""
    file_values = _parse_env_file(Path(env_file)) if env_file else {}
    env = os.environ if environ is None else environ
    merged = {**file_values, **{k: v for k, v in env.items() if k.startswith("LLM_")}}

    missing = [k for k in REQUIRED_KEYS if not merged.get(k, "").strip()]
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
        print(load_llm_config().describe())
    except ConfigError as exc:
        raise SystemExit(f"[config] {exc}")
