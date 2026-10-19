"""auth.py — Login OAuth Gmail untuk Gmail Inbox Manager (Fase 1.1).

Pemakaian:
    python auth.py login    # login pertama kali (membuka browser)
    python auth.py check    # tes kredensial dengan users.getProfile
    python auth.py logout   # cabut token dan hapus dari keyring

Di kode lain:
    from auth import get_credentials
    creds = get_credentials()                    # mode manual (boleh buka browser)
    creds = get_credentials(interactive=False)   # mode terjadwal (tanpa browser)

Prinsip keamanan (gate Fase 1):
- Token hanya disimpan di OS keyring, tidak pernah di file atau log.
- client_secret.json masuk .gitignore.
- Scope hanya gmail.modify.
"""

import argparse
import json
import logging
import sys

import keyring
import keyring.errors
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CLIENT_SECRET_FILE = "client_secret.json"
KEYRING_SERVICE = "gmail-inbox-manager"
KEYRING_USER = "oauth-token"

log = logging.getLogger("auth")


class ReauthRequired(RuntimeError):
    """Token tidak berlaku lagi dan login ulang butuh browser."""


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

def _login() -> Credentials:
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
    creds = _load()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except RefreshError as e:
            # Umumnya invalid_grant: token Testing lewat 7 hari, atau dicabut.
            log.warning("Refresh gagal (%s); perlu login ulang.", type(e).__name__)
            _delete()

    if not interactive:
        raise ReauthRequired("Perlu login ulang: jalankan `python auth.py login`.")

    creds = _login()
    
    _save(creds)
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
    print(f"OK. Akun: {profile['emailAddress']} | total pesan: {profile['messagesTotal']}")


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
        print(f"{CLIENT_SECRET_FILE} tidak ditemukan di folder ini.", file=sys.stderr)
        return 1
    except keyring.errors.NoKeyringError:
        print("Tidak ada backend keyring. Pasang keyrings.cryptfile (lihat panduan).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())