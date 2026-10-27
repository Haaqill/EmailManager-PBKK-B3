"""Pilih backend Gmail; mock tetap menjadi default yang aman untuk demo."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from app.config import _DOTENV_ONLY_KEYS
from app.gmail.client import GmailAPIClient
from app.gmail.mock_client import MockGmailAPIClient


class GmailConfigError(ValueError):
    """Konfigurasi backend Gmail tidak dikenal."""


def gmail_backend(secrets=None) -> str:
    """Resolve selection: process env, Streamlit secrets, .env, then mock.

    Streamlit auth/OIDC keys such as ``client_id`` are intentionally not used
    as Gmail credentials; Gmail OAuth uses the installed-app credentials file.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    dotenv_backend = dotenv_values(env_file).get("GMAIL_BACKEND", "")
    env_backend = os.getenv("GMAIL_BACKEND", "")
    if env_backend and (
        "GMAIL_BACKEND" not in _DOTENV_ONLY_KEYS
        or env_backend != dotenv_backend
    ):
        selected = env_backend
    else:
        secret_backend = None
        if secrets is not None:
            secret_backend = secrets.get("GMAIL_BACKEND")
            if not secret_backend:
                gmail_section = secrets.get("gmail", {})
                if hasattr(gmail_section, "get"):
                    secret_backend = gmail_section.get("backend")
        selected = secret_backend or env_backend or dotenv_backend or "mock"

    backend = str(selected).strip().lower()
    if backend not in {"mock", "gmail"}:
        raise GmailConfigError("GMAIL_BACKEND harus bernilai 'mock' atau 'gmail'.")
    return backend


def make_gmail_client(backend: str | None = None):
    """Buat Gmail client sesuai env; Gmail asli menuntut login yang sudah ada."""
    selected = backend or gmail_backend()
    if selected == "mock":
        return MockGmailAPIClient()
    if selected == "gmail":
        return GmailAPIClient(interactive=False)
    raise GmailConfigError("GMAIL_BACKEND harus bernilai 'mock' atau 'gmail'.")
