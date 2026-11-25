from __future__ import annotations

from http.client import HTTPConnection
import json
import logging
import threading

import keyring.errors
import pytest

from app.gmail import auth


class _Credentials:
    def __init__(self, *, valid: bool, expired: bool, refresh_token: str | None):
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.token = "access-token"

    def refresh(self, request) -> None:
        response = request("https://oauth.example.test/token", method="POST")
        del response
        self.valid = True
        self.expired = False

    def to_json(self) -> str:
        return json.dumps({"token": "access-token"})


class _Flow:
    def __init__(
        self,
        state: str,
        credentials: _Credentials | None = None,
        fetch_error: Exception | None = None,
    ):
        self.state = state
        self.redirect_uri = ""
        self.credentials = credentials or _Credentials(
            valid=True, expired=False, refresh_token="refresh-token"
        )
        self.fetch_error = fetch_error
        self.fetch_calls = []

    def authorization_url(self, **kwargs):
        assert kwargs == {"prompt": "consent"}
        return f"https://accounts.example.test/auth?state={self.state}", self.state

    def fetch_token(self, **kwargs):
        self.fetch_calls.append(kwargs)
        if self.fetch_error:
            raise self.fetch_error


@pytest.fixture
def oauth_setup(tmp_path, monkeypatch):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text(
        json.dumps({"installed": {"client_id": "test-client"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "CLIENT_SECRET_FILE", credentials_file)
    keyring = {}
    monkeypatch.setattr(
        auth.keyring,
        "get_password",
        lambda service, username: keyring.get(username),
    )
    monkeypatch.setattr(
        auth.keyring,
        "set_password",
        lambda service, username, value: keyring.__setitem__(username, value),
    )
    flows = []

    def create_flow(path, scopes, **kwargs):
        assert scopes == auth.SCOPES
        assert kwargs == {"autogenerate_code_verifier": True}
        flow = _Flow(f"state-{len(flows) + 1}")
        flows.append(flow)
        return flow

    monkeypatch.setattr(
        auth.InstalledAppFlow, "from_client_secrets_file", create_flow
    )

    yield keyring, flows

    with auth._pending_logins_lock:
        pending = list(auth._pending_logins.values())
        auth._pending_logins.clear()
    for login in pending:
        auth._stop_pending_login(login)


def _callback(pending, *, state: str | None = None, code: str = "code-canary"):
    port = pending.server.server_port
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "GET",
            f"/?code={code}&state={state or pending.state}",
            headers={"Host": f"localhost:{port}"},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        return response.status, body
    finally:
        connection.close()


def _wait_for_thread(thread: threading.Thread | None) -> None:
    assert thread is not None
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_begin_login_mengembalikan_url_dan_menyimpan_token_setelah_callback(
    oauth_setup, caplog
):
    keyring, flows = oauth_setup
    keyring["oauth-token:alice"] = "token-lama"
    caplog.set_level(logging.DEBUG)

    auth_url = auth.begin_login("alice")
    pending = auth._pending_logins["alice"]

    assert auth_url.startswith("https://accounts.example.test/auth?")
    assert pending.flow.redirect_uri.startswith("http://localhost:")
    assert pending.flow.redirect_uri.endswith("/")
    assert keyring == {"oauth-token:alice": "token-lama"}
    status, page = _callback(pending)
    _wait_for_thread(pending.thread)

    assert status == 200
    assert page == "Login berhasil. Jendela ini boleh ditutup."
    assert keyring == {
        "oauth-token:alice": json.dumps({"token": "access-token"})
    }
    assert flows[0].fetch_calls == [
        {
            "authorization_response": pending.flow.redirect_uri.replace(
                "http://", "https://"
            )
            + "?code=code-canary&state=state-1",
            "audience": None,
            "timeout": auth.LOGIN_TOKEN_TIMEOUT_S,
        }
    ]
    log_text = caplog.text
    assert auth_url not in log_text
    assert "code-canary" not in log_text


def test_login_baru_menggantikan_login_lama_untuk_user_yang_sama(oauth_setup):
    keyring, _ = oauth_setup

    first_url = auth.begin_login("alice")
    first = auth._pending_logins["alice"]
    second_url = auth.begin_login("alice")
    second = auth._pending_logins["alice"]

    assert first_url != second_url
    assert first is not second
    _wait_for_thread(first.thread)
    assert first.server.fileno() == -1
    assert second.thread is not None and second.thread.is_alive()
    _callback(second)
    _wait_for_thread(second.thread)
    assert keyring["oauth-token:alice"] == json.dumps({"token": "access-token"})


def test_login_untuk_user_berbeda_tidak_saling_mengganggu(oauth_setup):
    keyring, _ = oauth_setup

    auth.begin_login("alice")
    alice = auth._pending_logins["alice"]
    auth.begin_login("bob")
    bob = auth._pending_logins["bob"]

    assert alice.thread is not None and alice.thread.is_alive()
    assert bob.thread is not None and bob.thread.is_alive()
    _callback(bob)
    _callback(alice)
    _wait_for_thread(alice.thread)
    _wait_for_thread(bob.thread)
    assert set(keyring) == {"oauth-token:alice", "oauth-token:bob"}


def test_login_timeout_menutup_thread_dan_socket_tanpa_menyimpan(
    oauth_setup, monkeypatch
):
    keyring, _ = oauth_setup
    monkeypatch.setattr(auth, "LOGIN_TIMEOUT_S", 0.15)

    auth.begin_login("alice")
    pending = auth._pending_logins["alice"]
    _wait_for_thread(pending.thread)

    assert pending.server.fileno() == -1
    assert "alice" not in auth._pending_logins
    assert keyring == {}


@pytest.mark.parametrize(
    ("wrong_state", "fetch_error"),
    [(True, None), (False, RuntimeError("detail token rahasia"))],
)
def test_callback_gagal_tidak_menyimpan_token(
    oauth_setup, monkeypatch, caplog, wrong_state, fetch_error
):
    keyring, _ = oauth_setup
    flow = _Flow("state-1")
    flow.fetch_error = fetch_error
    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_secrets_file",
        lambda *args, **kwargs: flow,
    )
    caplog.set_level(logging.DEBUG)
    auth.begin_login("alice")
    pending = auth._pending_logins["alice"]

    _callback(pending, state="wrong-state" if wrong_state else pending.state)
    _wait_for_thread(pending.thread)

    assert keyring == {}
    assert "code-canary" not in caplog.text
    assert "accounts.example.test" not in caplog.text
    if fetch_error:
        assert "RuntimeError" in caplog.text
        assert "detail token rahasia" not in caplog.text


def test_client_web_ditolak_sebelum_server_dibuka(oauth_setup, monkeypatch, tmp_path):
    credentials_file = tmp_path / "web-credentials.json"
    credentials_file.write_text(
        json.dumps({"web": {"client_id": "web-client"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "CLIENT_SECRET_FILE", credentials_file)
    monkeypatch.setattr(
        auth.simple_server,
        "make_server",
        lambda *args, **kwargs: pytest.fail("server tidak boleh dibuka"),
    )

    with pytest.raises(auth.OAuthConfigurationError):
        auth.begin_login("alice")


def test_status_token_kosong_atau_rusak_menjadi_not_connected(oauth_setup):
    keyring, _ = oauth_setup

    assert auth.auth_status("alice") == "not_connected"
    keyring["oauth-token:alice"] = "bukan-json"
    assert auth.auth_status("alice") == "not_connected"


def test_status_kredensial_valid_menjadi_connected(monkeypatch):
    creds = _Credentials(valid=True, expired=False, refresh_token="refresh")
    monkeypatch.setattr(auth, "_load", lambda user_id: creds)

    assert auth.auth_status("alice") == "connected"


def test_status_refresh_sukses_menyimpan_token(monkeypatch):
    creds = _Credentials(valid=False, expired=True, refresh_token="refresh")
    saved = []
    requests = []
    monkeypatch.setattr(auth, "_load", lambda user_id: creds)
    monkeypatch.setattr(
        auth,
        "Request",
        lambda: lambda url, **kwargs: requests.append(
            {"url": url, **kwargs}
        ),
    )
    monkeypatch.setattr(auth, "_save", lambda value, user_id: saved.append((value, user_id)))

    assert auth.auth_status("alice") == "connected"
    assert requests == [
        {
            "url": "https://oauth.example.test/token",
            "method": "POST",
            "timeout": auth.AUTH_STATUS_REFRESH_TIMEOUT_S,
        }
    ]
    assert saved == [(creds, "alice")]


def test_status_refresh_gagal_expired_dan_token_tidak_dihapus(monkeypatch):
    creds = _Credentials(valid=False, expired=True, refresh_token="refresh")
    stored = {"oauth-token:alice": "token-yang-ada"}
    deleted = []

    def refresh(request):
        raise auth.RefreshError("refresh token rahasia")

    creds.refresh = refresh
    monkeypatch.setattr(auth, "_load", lambda user_id: creds)
    monkeypatch.setattr(auth, "_delete", lambda user_id: deleted.append(user_id))

    assert auth.auth_status("alice") == "expired"
    assert stored["oauth-token:alice"] == "token-yang-ada"
    assert deleted == []


def test_status_expired_tanpa_refresh_token(monkeypatch):
    creds = _Credentials(valid=False, expired=True, refresh_token=None)
    monkeypatch.setattr(auth, "_load", lambda user_id: creds)
    monkeypatch.setattr(
        auth, "Request", lambda **kwargs: pytest.fail("refresh tidak diharapkan")
    )

    assert auth.auth_status("alice") == "expired"


def test_status_tanpa_keyring_melempar_reauth_required(monkeypatch):
    def fail_load(user_id):
        raise keyring.errors.NoKeyringError()

    monkeypatch.setattr(auth, "_load", fail_load)

    with pytest.raises(auth.ReauthRequired):
        auth.auth_status("alice")
