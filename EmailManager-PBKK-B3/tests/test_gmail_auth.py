from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from app.gmail import auth
from app.gmail.factory import GmailConfigError, gmail_backend, make_gmail_client
from app.gmail.mock_client import MockGmailAPIClient


def test_oauth_uses_minimal_required_scope_and_local_keyring():
    assert auth.SCOPES == ["https://www.googleapis.com/auth/gmail.modify"]
    assert auth.KEYRING_SERVICE == "gmail-inbox-manager"
    assert auth.CLIENT_SECRET_FILE.name == "credentials.json"
    assert auth.OAUTH_REDIRECT_HOST == "localhost"


def test_web_client_json_is_rejected_for_desktop_flow(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"web": {"client_id": "redacted"}}), encoding="utf-8")
    monkeypatch.setattr(auth, "CLIENT_SECRET_FILE", credentials)

    with pytest.raises(auth.OAuthConfigurationError, match="Web application"):
        auth._validate_desktop_client_file()


def test_desktop_flow_uses_dynamic_localhost_redirect(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"installed": {"client_id": "redacted"}}), encoding="utf-8")
    monkeypatch.setattr(auth, "CLIENT_SECRET_FILE", credentials)
    calls = {}

    class Flow:
        def run_local_server(self, **kwargs):
            calls.update(kwargs)
            return "credentials"

    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_secrets_file",
        lambda path, scopes, **kwargs: Flow(),
    )
    assert auth._login() == "credentials"
    assert calls["host"] == "localhost"
    assert calls["port"] == 0
    assert calls["redirect_uri_trailing_slash"] is True


def test_get_credentials_reuses_valid_local_credential(monkeypatch):
    creds = SimpleNamespace(valid=True)
    monkeypatch.setattr(auth, "_load", lambda: creds)
    monkeypatch.setattr(auth, "_login", lambda: pytest.fail("unexpected browser login"))

    assert auth.get_credentials(interactive=False) is creds


def test_get_credentials_expired_token_refreshes_and_persists(monkeypatch):
    class Credentials:
        valid = False
        expired = True
        refresh_token = "refresh"

        def refresh(self, request):
            self.valid = True

    creds = Credentials()
    calls = []
    monkeypatch.setattr(auth, "_load", lambda: creds)
    monkeypatch.setattr(auth, "Request", lambda: "request")
    monkeypatch.setattr(auth, "_save", lambda value: calls.append(value))

    assert auth.get_credentials(interactive=False) is creds
    assert calls == [creds]


def test_missing_credentials_require_explicit_login(monkeypatch):
    monkeypatch.setattr(auth, "_load", lambda: None)
    with pytest.raises(auth.ReauthRequired, match="login"):
        auth.get_credentials(interactive=False)


def test_gmail_backend_defaults_to_mock_and_can_select_real_gmail(monkeypatch):
    monkeypatch.delenv("GMAIL_BACKEND", raising=False)
    assert gmail_backend() == "mock"
    assert isinstance(make_gmail_client(), MockGmailAPIClient)
    monkeypatch.setenv("GMAIL_BACKEND", "gmail")
    assert gmail_backend() == "gmail"


def test_gmail_backend_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("GMAIL_BACKEND", "auto")
    with pytest.raises(GmailConfigError, match="mock.*gmail"):
        gmail_backend()


def test_streamlit_secret_can_select_gmail_over_dotenv_default(monkeypatch):
    monkeypatch.delenv("GMAIL_BACKEND", raising=False)
    assert gmail_backend({"GMAIL_BACKEND": "gmail"}) == "gmail"
    assert gmail_backend({"gmail": {"backend": "gmail"}}) == "gmail"


def test_explicit_environment_backend_takes_precedence_over_streamlit_secret(monkeypatch):
    monkeypatch.setenv("GMAIL_BACKEND", "gmail")
    assert gmail_backend({"GMAIL_BACKEND": "mock"}) == "gmail"


def test_gmail_backend_constructs_real_client_without_implicit_browser(monkeypatch):
    monkeypatch.setenv("GMAIL_BACKEND", "gmail")
    seen = []
    monkeypatch.setattr(
        "app.gmail.factory.GmailAPIClient",
        lambda **kwargs: seen.append(kwargs) or "gmail-client",
    )
    assert make_gmail_client() == "gmail-client"
    assert seen == [{"interactive": False}]
