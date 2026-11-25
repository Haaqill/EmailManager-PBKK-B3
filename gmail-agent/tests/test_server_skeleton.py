from __future__ import annotations

import logging
from concurrent.futures import Executor

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.server import app as server_app
from app.server.app import create_app, get_current_user
from app.server.errors import AgentError
from app.server.settings import Settings

_TOKEN = "t" * 40


class RegistryPalsu:
    def __init__(self) -> None:
        self.reconcile_calls = 0

    def reconcile_on_start(self) -> None:
        self.reconcile_calls += 1


class ExecutorSinkron(Executor):
    def __init__(self) -> None:
        self.shutdown_dipanggil = False

    def submit(self, fn, /, *args, **kwargs):
        return None

    def shutdown(self, wait=True, *, cancel_futures=False) -> None:
        self.shutdown_dipanggil = True


class ModelValidasi(BaseModel):
    draft: int


def _buat_app(executor: Executor | None = None):
    registry = RegistryPalsu()
    app = create_app(
        Settings(agent_token=_TOKEN),
        registry,
        llm_factory=lambda: object(),
        gmail_factory=lambda: object(),
        executor=executor,
    )
    return app, registry


def _pasang_route_uji(app: FastAPI) -> None:
    @app.get("/uji/pengguna")
    async def pengguna(user_id: str = Depends(get_current_user)):
        return {"user_id": user_id}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer salah" + "x" * 32, "X-User-Id": "123"},
        {"Authorization": b"Bearer \xff", "X-User-Id": "123"},
    ],
)
def test_token_tidak_valid_mendapat_401(headers):
    app, _ = _buat_app()
    _pasang_route_uji(app)

    with TestClient(app) as client:
        response = client.get("/uji/pengguna", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "unauthorized",
            "message": "Autentikasi diperlukan.",
        }
    }


def test_token_valid_mengembalikan_id_pengguna():
    app, _ = _buat_app()
    _pasang_route_uji(app)

    with TestClient(app) as client:
        response = client.get(
            "/uji/pengguna",
            headers={"Authorization": f"Bearer {_TOKEN}", "X-User-Id": "123"},
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": "123"}


def test_autentikasi_memakai_compare_digest(monkeypatch):
    panggilan = []
    fungsi_asli = server_app.secrets.compare_digest

    def spy(nilai, pembanding):
        panggilan.append((nilai, pembanding))
        return fungsi_asli(nilai, pembanding)

    monkeypatch.setattr(server_app.secrets, "compare_digest", spy)
    app, _ = _buat_app()
    _pasang_route_uji(app)

    with TestClient(app) as client:
        client.get(
            "/uji/pengguna",
            headers={"Authorization": f"Bearer {_TOKEN}", "X-User-Id": "123"},
        )

    assert panggilan == [(_TOKEN.encode(), _TOKEN.encode())]


@pytest.mark.parametrize("user_id", [None, "abc", "../x", "1" * 19])
def test_id_pengguna_tidak_valid_mendapat_422(user_id):
    app, _ = _buat_app()
    _pasang_route_uji(app)
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    if user_id is not None:
        headers["X-User-Id"] = user_id

    with TestClient(app) as client:
        response = client.get("/uji/pengguna", headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_token_diperiksa_sebelum_id_pengguna():
    app, _ = _buat_app()
    _pasang_route_uji(app)

    with TestClient(app) as client:
        response = client.get(
            "/uji/pengguna",
            headers={"Authorization": "Bearer salah"},
        )

    assert response.status_code == 401


def test_galat_validasi_tidak_mengembalikan_nilai_input():
    app, _ = _buat_app()

    @app.post("/uji/validasi")
    async def validasi(body: ModelValidasi):
        return {"ok": True}

    canary = "isi-draf-sensitif-9bf18d"
    with TestClient(app) as client:
        response = client.post("/uji/validasi", json={"draft": canary})

    assert response.status_code == 422
    assert canary not in response.text
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Permintaan tidak valid."}
    }


def test_galat_internal_tidak_membocorkan_pesan(caplog):
    app, _ = _buat_app()
    canary = "rahasia-82c1e0"

    @app.get("/uji/internal")
    async def internal():
        raise RuntimeError(canary)

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR):
            response = client.get("/uji/internal")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Kesalahan internal."}
    }
    assert canary not in response.text
    assert canary not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("token", ["", "pendek"])
def test_settings_menolak_token_kosong_atau_pendek(token):
    with pytest.raises(ValueError) as error:
        Settings.from_env({"AGENT_TOKEN": token})

    if token:
        assert token not in str(error.value)
    assert "AGENT_TOKEN" in str(error.value)


def test_settings_membaca_default_dan_host_tetap_loopback():
    settings = Settings.from_env(
        {
            "AGENT_TOKEN": _TOKEN,
            "AGENT_HOST": "0.0.0.0",
        }
    )

    assert settings.agent_port == 8765
    assert settings.agent_registry_path == ""
    assert settings.host == "127.0.0.1"


def test_dokumentasi_dan_openapi_dimatikan():
    app, _ = _buat_app()

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/redoc").status_code == 404


def test_lifespan_merekonsiliasi_registry_dan_mematikan_executor(monkeypatch):
    executor = ExecutorSinkron()
    app, registry = _buat_app(executor)
    register_calls = []
    monkeypatch.setattr(
        server_app,
        "register_all_tools",
        lambda: register_calls.append(True),
    )

    with TestClient(app):
        assert registry.reconcile_calls == 1
        assert register_calls == [True]

    assert executor.shutdown_dipanggil


def test_pasangan_status_dan_kode_galat_dibatasi():
    with pytest.raises(ValueError):
        AgentError(401, "invalid_request", "Pesan.")
