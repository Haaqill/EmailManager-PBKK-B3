"""auth.py — Login OAuth Gmail untuk Gmail Inbox Manager (Fase 1.1).

Pemakaian:
    python -m app.gmail.auth login    # login pertama kali (membuka browser)
    python -m app.gmail.auth check    # tes kredensial dengan users.getProfile
    python -m app.gmail.auth logout   # cabut token dan hapus dari keyring

Di kode lain:
    from app.gmail.auth import get_credentials
    creds = get_credentials()                    # mode manual (boleh buka browser)
    creds = get_credentials(interactive=False)   # mode terjadwal (tanpa browser)

Prinsip keamanan (gate Fase 1):
- Token hanya disimpan di OS keyring, tidak pernah di file atau log.
- credentials.json masuk .gitignore.
- Scope hanya gmail.modify.
"""

import argparse
from dataclasses import dataclass
import hmac
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
from typing import Literal
from urllib.parse import parse_qs, urlsplit, urlunsplit
from wsgiref import simple_server, util

import keyring
import keyring.errors
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CLIENT_SECRET_FILE = Path(__file__).resolve().parents[2] / "credentials.json"
# InstalledAppFlow chooses a free loopback port at runtime. The exact URI sent
# in the authorization request is therefore http://localhost:<free-port>/.
OAUTH_REDIRECT_HOST = "localhost"
KEYRING_SERVICE = "gmail-inbox-manager"
KEYRING_USER_PREFIX = "oauth-token"
DEFAULT_USER_ID = "dev"
LOGIN_TIMEOUT_S = 300
LOGIN_POLL_INTERVAL_S = 0.1
AUTH_STATUS_REFRESH_TIMEOUT_S = 5
LOGIN_TOKEN_TIMEOUT_S = 10
_USER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

log = logging.getLogger("auth")
_pending_logins: dict[str, "_PendingLogin"] = {}
_pending_logins_lock = threading.Lock()


class ReauthRequired(RuntimeError):
    """Token tidak berlaku lagi dan login ulang butuh browser."""


class OAuthConfigurationError(RuntimeError):
    """credentials.json is not an OAuth Desktop/Installed application config."""


class _QuietRequestHandler(simple_server.WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class _OAuthRedirectApp:
    def __init__(self) -> None:
        self.authorization_response: str | None = None

    def __call__(self, environ: dict, start_response):
        if environ.get("REQUEST_METHOD") != "GET" or environ.get("PATH_INFO") != "/":
            body = b"Not found."
            start_response(
                "404 Not Found",
                [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
            )
            return [body]

        self.authorization_response = util.request_uri(environ)
        body = "Login berhasil. Jendela ini boleh ditutup.".encode("utf-8")
        start_response(
            "200 OK",
            [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]


@dataclass
class _PendingLogin:
    server: simple_server.WSGIServer
    app: _OAuthRedirectApp
    flow: InstalledAppFlow
    state: str
    cancelled: threading.Event
    thread: threading.Thread | None = None


# ---------- penyimpanan token (keyring) ----------

def keyring_username(user_id: str) -> str:
    if not isinstance(user_id, str) or not _USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError("ID pengguna tidak valid.")
    return f"{KEYRING_USER_PREFIX}:{user_id}"


def _load(user_id: str = DEFAULT_USER_ID) -> Credentials | None:
    raw = keyring.get_password(KEYRING_SERVICE, keyring_username(user_id))
    if not raw:
        return None
    try:
        return Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    except (ValueError, KeyError):
        log.warning("Data token di keyring rusak; perlu login ulang.")
        return None


def _save(creds: Credentials, user_id: str = DEFAULT_USER_ID) -> None:
    keyring.set_password(KEYRING_SERVICE, keyring_username(user_id), creds.to_json())


def _delete(user_id: str = DEFAULT_USER_ID) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, keyring_username(user_id))
    except keyring.errors.PasswordDeleteError:
        pass


# ---------- alur OAuth ----------

def _validate_desktop_client_file() -> None:
    """Reject Web application credentials before opening a browser.

    The Streamlit ``[auth]`` redirect_uri is unrelated to Gmail API OAuth.
    Keeping this check here prevents a confusing Google 400 response when a
    Web client JSON was downloaded accidentally.
    """
    try:
        config = json.loads(CLIENT_SECRET_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OAuthConfigurationError):
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise OAuthConfigurationError(
            "credentials.json tidak dapat dibaca sebagai konfigurasi OAuth Google."
        ) from None
    if not isinstance(config, dict) or not isinstance(config.get("installed"), dict):
        if isinstance(config, dict) and isinstance(config.get("web"), dict):
            raise OAuthConfigurationError(
                "credentials.json adalah OAuth Web application. Unduh OAuth client "
                "Desktop app untuk flow browser lokal ini."
            )
        raise OAuthConfigurationError(
            "credentials.json harus berasal dari OAuth client Desktop app."
        )

def _login() -> Credentials:
    # InstalledAppFlow's callback URL contains a one-time authorization code.
    # Keep the OAuth library from logging it when login is started from Streamlit.
    logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.WARNING)
    _validate_desktop_client_file()
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        SCOPES,
        # PKCE ditulis eksplisit: nilai default berbeda antar versi library.
        autogenerate_code_verifier=True,
    )
    # port=0 -> loopback di port acak yang kosong.
    # prompt="consent" memastikan Google memberi refresh token baru.
    return flow.run_local_server(
        port=0,
        host=OAUTH_REDIRECT_HOST,
        redirect_uri_trailing_slash=True,
        prompt="consent",
        open_browser=True,
        authorization_prompt_message="Buka URL ini jika browser tidak terbuka otomatis:\n{url}",
        success_message="Login berhasil. Jendela ini boleh ditutup.",
    )


def auth_status(user_id: str) -> Literal["connected", "not_connected", "expired"]:
    try:
        creds = _load(user_id)
    except keyring.errors.NoKeyringError:
        raise ReauthRequired(
            "Tidak ada backend keyring lokal. Aktifkan keyring sistem sebelum login Gmail."
        ) from None

    if creds is None:
        return "not_connected"
    if creds.valid:
        return "connected"
    if not creds.expired:
        return "not_connected"
    if not creds.refresh_token:
        return "expired"

    try:
        request = Request()
        creds.refresh(
            lambda url, **kwargs: request(
                url, timeout=AUTH_STATUS_REFRESH_TIMEOUT_S, **kwargs
            )
        )
    except RefreshError as exc:
        log.warning("Pemeriksaan refresh gagal (%s).", type(exc).__name__)
        return "expired"

    try:
        _save(creds, user_id)
    except keyring.errors.NoKeyringError:
        raise ReauthRequired(
            "Tidak ada backend keyring lokal untuk menyimpan sesi Gmail."
        ) from None
    return "connected" if creds.valid else "expired"


def _close_pending_server(pending: _PendingLogin) -> None:
    try:
        pending.server.server_close()
    except OSError:
        pass


def _complete_login(user_id: str, pending: _PendingLogin) -> None:
    try:
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while (
            not pending.cancelled.is_set()
            and pending.app.authorization_response is None
            and time.monotonic() < deadline
        ):
            pending.server.timeout = min(
                LOGIN_POLL_INTERVAL_S, max(0, deadline - time.monotonic())
            )
            pending.server.handle_request()

        if pending.cancelled.is_set():
            return
        if pending.app.authorization_response is None:
            raise TimeoutError

        redirect_uri = urlsplit(pending.flow.redirect_uri)
        authorization_response = urlsplit(pending.app.authorization_response)
        query = parse_qs(authorization_response.query, keep_blank_values=True)
        states = query.get("state", [])
        if (
            authorization_response.netloc != redirect_uri.netloc
            or authorization_response.path != "/"
            or len(states) != 1
            or not hmac.compare_digest(states[0], pending.state)
            or not query.get("code", [""])[0]
            or query.get("error")
        ):
            raise ValueError("Respons OAuth tidak valid.")

        # run_local_server menyajikan callback HTTP tetapi meminta oauthlib
        # menukarkan kode melalui URI HTTPS agar lolos validasi secure transport.
        secure_response = urlunsplit(
            authorization_response._replace(scheme="https")
        )
        pending.flow.fetch_token(
            authorization_response=secure_response,
            audience=None,
            timeout=LOGIN_TOKEN_TIMEOUT_S,
        )
        creds = pending.flow.credentials
        with _pending_logins_lock:
            if (
                _pending_logins.get(user_id) is pending
                and not pending.cancelled.is_set()
            ):
                _save(creds, user_id)
    except Exception as exc:
        if not pending.cancelled.is_set():
            log.warning("Login OAuth latar belakang gagal (%s).", type(exc).__name__)
    finally:
        _close_pending_server(pending)
        with _pending_logins_lock:
            if _pending_logins.get(user_id) is pending:
                _pending_logins.pop(user_id, None)


def _stop_pending_login(pending: _PendingLogin) -> None:
    pending.cancelled.set()
    _close_pending_server(pending)
    if pending.thread is not None:
        pending.thread.join(timeout=LOGIN_POLL_INTERVAL_S * 5)


def begin_login(user_id: str) -> str:
    logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.WARNING)
    _validate_desktop_client_file()
    keyring_username(user_id)
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        SCOPES,
        autogenerate_code_verifier=True,
    )
    redirect_app = _OAuthRedirectApp()
    server = simple_server.make_server(
        OAUTH_REDIRECT_HOST,
        0,
        redirect_app,
        handler_class=_QuietRequestHandler,
    )
    server.timeout = LOGIN_POLL_INTERVAL_S
    try:
        flow.redirect_uri = (
            f"http://{OAUTH_REDIRECT_HOST}:{server.server_port}/"
        )
        auth_url, state = flow.authorization_url(prompt="consent")
    except Exception:
        server.server_close()
        raise

    pending = _PendingLogin(
        server=server,
        app=redirect_app,
        flow=flow,
        state=state,
        cancelled=threading.Event(),
    )
    thread = threading.Thread(
        target=_complete_login,
        args=(user_id, pending),
        name=f"gmail-oauth-{user_id}",
        daemon=True,
    )
    pending.thread = thread

    with _pending_logins_lock:
        previous = _pending_logins.get(user_id)
        if previous is not None:
            previous.cancelled.set()
        _pending_logins[user_id] = pending
        try:
            thread.start()
        except Exception:
            _pending_logins.pop(user_id, None)
            _close_pending_server(pending)
            raise
    if previous is not None:
        _stop_pending_login(previous)
    return auth_url


def get_credentials(
    interactive: bool = True, user_id: str = DEFAULT_USER_ID
) -> Credentials:
    """Kembalikan kredensial yang valid.

    interactive=False dipakai untuk run terjadwal (Fase 3): tidak membuka
    browser, tapi melempar ReauthRequired agar bisa dilaporkan ke pengguna.
    """
    try:
        creds = _load(user_id)
    except keyring.errors.NoKeyringError:
        raise ReauthRequired(
            "Tidak ada backend keyring lokal. Aktifkan keyring sistem sebelum login Gmail."
        ) from None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            try:
                _save(creds, user_id)
            except keyring.errors.NoKeyringError:
                raise ReauthRequired(
                    "Tidak ada backend keyring lokal untuk menyimpan sesi Gmail."
                ) from None
            return creds
        except RefreshError as e:
            # Umumnya invalid_grant: token Testing lewat 7 hari, atau dicabut.
            log.warning("Refresh gagal (%s); perlu login ulang.", type(e).__name__)
            _delete(user_id)

    if not interactive:
        raise ReauthRequired("Perlu login ulang: jalankan `python -m app.gmail.auth login`.")

    try:
        creds = _login()
    except FileNotFoundError:
        raise
    except Exception:
        raise ReauthRequired(
            "OAuth Gmail gagal. Periksa konfigurasi OAuth, akses browser, dan koneksi."
        ) from None
    
    try:
        _save(creds, user_id)
    except keyring.errors.NoKeyringError:
        raise ReauthRequired(
            "Tidak ada backend keyring lokal untuk menyimpan sesi Gmail."
        ) from None
    return creds


def revoke_and_logout(user_id: str = DEFAULT_USER_ID) -> None:
    creds = _load(user_id)
    if creds:
        token = creds.refresh_token or creds.token
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        except requests.RequestException:
            log.warning("Gagal menghubungi endpoint revoke; token tetap dihapus lokal.")
    _delete(user_id)


# ---------- CLI ----------

def _check(user_id: str = DEFAULT_USER_ID) -> None:
    from googleapiclient.discovery import build

    creds = get_credentials(interactive=False, user_id=user_id)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    print(f"OK. Gmail OAuth aktif | total pesan: {profile['messagesTotal']}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Server loopback mencatat URL callback (berisi authorization code) di level INFO.
    # Dibisukan agar kode tidak muncul di terminal atau log.
    logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="OAuth Gmail Inbox Manager")
    parser.add_argument("command", choices=["login", "check", "logout"])
    parser.add_argument("--user", default=DEFAULT_USER_ID)
    args = parser.parse_args()

    try:
        if args.command == "login":
            get_credentials(interactive=True, user_id=args.user)
            print("Token tersimpan di keyring.")
        elif args.command == "check":
            _check(user_id=args.user)
        elif args.command == "logout":
            revoke_and_logout(user_id=args.user)
            print("Token dicabut dan dihapus dari keyring.")
    except ReauthRequired as e:
        print(e, file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"{CLIENT_SECRET_FILE.name} tidak ditemukan di folder proyek.", file=sys.stderr)
        return 1
    except OAuthConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except keyring.errors.NoKeyringError:
        print("Tidak ada backend keyring. Pasang keyrings.cryptfile (lihat panduan).", file=sys.stderr)
        return 1
    except Exception:
        print("OAuth Gmail gagal. Periksa konfigurasi, jaringan, dan backend keyring.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
