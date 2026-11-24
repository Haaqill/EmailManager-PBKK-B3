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
    calls = []
    monkeypatch.setattr(
        auth, "_load", lambda *args, **kwargs: calls.append((args, kwargs)) or creds
    )
    monkeypatch.setattr(auth, "_login", lambda: pytest.fail("unexpected browser login"))

    assert auth.get_credentials(interactive=False, user_id="alice") is creds
    assert calls == [(("alice",), {})]


def test_get_credentials_expired_token_refreshes_and_persists(monkeypatch):
    class Credentials:
        valid = False
        expired = True
        refresh_token = "refresh"

        def refresh(self, request):
            self.valid = True

    creds = Credentials()
    calls = []
    monkeypatch.setattr(auth, "_load", lambda *args, **kwargs: creds)
    monkeypatch.setattr(auth, "Request", lambda: "request")
    monkeypatch.setattr(auth, "_save", lambda value, *args, **kwargs: calls.append(value))

    assert auth.get_credentials(interactive=False) is creds
    assert calls == [creds]


def test_missing_credentials_require_explicit_login(monkeypatch):
    monkeypatch.setattr(auth, "_load", lambda *args, **kwargs: None)
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
    assert make_gmail_client(user_id="alice") == "gmail-client"
    assert seen == [
        {"interactive": False, "user_id": "dev"},
        {"interactive": False, "user_id": "alice"},
    ]


def test_token_disimpan_di_entri_keyring_yang_berbeda_per_pengguna(monkeypatch):
    keyring = {}
    monkeypatch.setattr(
        auth.keyring, "get_password", lambda service, username: keyring.get(username)
    )
    monkeypatch.setattr(
        auth.keyring,
        "set_password",
        lambda service, username, value: keyring.__setitem__(username, value),
    )
    monkeypatch.setattr(
        auth.Credentials,
        "from_authorized_user_info",
        classmethod(lambda cls, info, scopes: info["token"]),
    )

    auth._save(SimpleNamespace(to_json=lambda: json.dumps({"token": "token-a"})), "alice")
    auth._save(SimpleNamespace(to_json=lambda: json.dumps({"token": "token-b"})), "bob")

    assert set(keyring) == {"oauth-token:alice", "oauth-token:bob"}
    assert auth._load("alice") == "token-a"
    assert auth._load("bob") == "token-b"


def test_logout_pengguna_tidak_menghapus_token_pengguna_lain(monkeypatch):
    keyring = {
        "oauth-token:alice": json.dumps({"token": "token-a"}),
        "oauth-token:bob": json.dumps({"token": "token-b"}),
    }
    monkeypatch.setattr(
        auth.keyring, "get_password", lambda service, username: keyring.get(username)
    )
    monkeypatch.setattr(
        auth.keyring,
        "delete_password",
        lambda service, username: keyring.pop(username),
    )
    monkeypatch.setattr(
        auth.Credentials,
        "from_authorized_user_info",
        classmethod(
            lambda cls, info, scopes: SimpleNamespace(
                refresh_token=info["token"], token=info["token"]
            )
        ),
    )
    monkeypatch.setattr(auth.requests, "post", lambda *args, **kwargs: None)

    auth.revoke_and_logout("alice")

    assert "oauth-token:alice" not in keyring
    assert keyring["oauth-token:bob"] == json.dumps({"token": "token-b"})


@pytest.mark.parametrize("user_id", ["user name", "user/name", "user:name", "", "a" * 65])
def test_id_pengguna_tidak_valid_ditolak_tanpa_membocorkan_nilai(user_id):
    with pytest.raises(ValueError) as error:
        auth.keyring_username(user_id)

    assert str(error.value) == "ID pengguna tidak valid."
    if user_id:
        assert user_id not in str(error.value)


@pytest.mark.parametrize(
    ("command", "handler"),
    [
        ("login", "get_credentials"),
        ("check", "_check"),
        ("logout", "revoke_and_logout"),
    ],
)
def test_cli_meneruskan_user_yang_diberikan(monkeypatch, command, handler):
    calls = []
    monkeypatch.setattr(auth.sys, "argv", ["auth", command, "--user", "alice"])
    monkeypatch.setattr(auth, "get_credentials", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(auth, "_check", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(auth, "revoke_and_logout", lambda **kwargs: calls.append(kwargs))

    assert auth.main() == 0
    assert calls == [
        {"interactive": True, "user_id": "alice"}
        if handler == "get_credentials"
        else {"user_id": "alice"}
    ]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("login", {"interactive": True, "user_id": "dev"}),
        ("check", {"user_id": "dev"}),
        ("logout", {"user_id": "dev"}),
    ],
)
def test_cli_memakai_user_dev_bila_tidak_diberikan(monkeypatch, command, expected):
    calls = []
    monkeypatch.setattr(auth.sys, "argv", ["auth", command])
    monkeypatch.setattr(auth, "get_credentials", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(auth, "_check", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(auth, "revoke_and_logout", lambda **kwargs: calls.append(kwargs))

    assert auth.main() == 0
    assert calls == [expected]
