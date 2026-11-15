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
import json
import logging
from pathlib import Path
import sys

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
KEYRING_USER = "oauth-token"

log = logging.getLogger("auth")


class ReauthRequired(RuntimeError):
    """Token tidak berlaku lagi dan login ulang butuh browser."""


class OAuthConfigurationError(RuntimeError):
    """credentials.json is not an OAuth Desktop/Installed application config."""


# ---------- penyimpanan token (keyring) ----------

def _load() -> Credentials | None:
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not raw:
        return None
    try:
        return Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    except (ValueError, KeyError):
        log.warning("Data token di keyring rusak; perlu login ulang.")
        return None


def _save(creds: Credentials) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, creds.to_json())


def _delete() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
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


def get_credentials(interactive: bool = True) -> Credentials:
    """Kembalikan kredensial yang valid.

    interactive=False dipakai untuk run terjadwal (Fase 3): tidak membuka
    browser, tapi melempar ReauthRequired agar bisa dilaporkan ke pengguna.
    """
    try:
        creds = _load()
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
                _save(creds)
            except keyring.errors.NoKeyringError:
                raise ReauthRequired(
                    "Tidak ada backend keyring lokal untuk menyimpan sesi Gmail."
                ) from None
            return creds
        except RefreshError as e:
            # Umumnya invalid_grant: token Testing lewat 7 hari, atau dicabut.
            log.warning("Refresh gagal (%s); perlu login ulang.", type(e).__name__)
            _delete()

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
        _save(creds)
    except keyring.errors.NoKeyringError:
        raise ReauthRequired(
            "Tidak ada backend keyring lokal untuk menyimpan sesi Gmail."
        ) from None
    return creds


def revoke_and_logout() -> None:
    creds = _load()
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
    _delete()


# ---------- CLI ----------

def _check() -> None:
    from googleapiclient.discovery import build

    creds = get_credentials(interactive=False)
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
    args = parser.parse_args()

    try:
        if args.command == "login":
            get_credentials(interactive=True)
            print("Token tersimpan di keyring.")
        elif args.command == "check":
            _check()
        elif args.command == "logout":
            revoke_and_logout()
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
