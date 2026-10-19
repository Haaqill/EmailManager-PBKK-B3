"""Tes bahwa semua stub bisa di-import tanpa error.

Tujuan: memastikan modul yang nanti ditulis B/C/D bisa meng-import
satu sama lain tanpa ModuleNotFoundError atau ImportError.
"""


def test_import_semua_modul():
    import app.config
    import app.contracts
    import app.logging_setup
    import app.agent.dispatcher
    import app.agent.graph
    import app.agent.prompts
    import app.agent.state
    import app.gmail.client
    import app.gmail.mock_client
    import app.gmail.schemas
    import app.gmail.tools
    import app.llm.campus
    import app.llm.client
    import app.llm.mock
    import app.privacy.injection
    import app.privacy.redact
    import app.ui.streamlit_app  # noqa: F401


def test_redact_stub_mengembalikan_teks():
    """Stub redact harus pass-through agar B bisa jalan."""
    from app.privacy.redact import redact, restore, pii_map_for, html_to_text

    peta = pii_map_for("batch-1")
    assert redact("halo dunia", peta) == "halo dunia"
    assert restore("halo dunia", peta) == "halo dunia"
    assert html_to_text("<p>halo</p>") == "<p>halo</p>"


def test_injection_stub_mengembalikan_teks():
    from app.privacy.injection import wrap_email_content

    assert wrap_email_content("halo") == "halo"


def test_logger_stub_ada():
    from app.logging_setup import get_logger

    logger = get_logger()
    assert logger is not None


def test_stub_raise_not_implemented():
    """Stub kelas yang belum diisi harus raise NotImplementedError."""
    import pytest

    from app.llm.campus import CampusLLM
    from app.gmail.client import GmailAPIClient
    from app.gmail.mock_client import MockGmailAPIClient
    from app.agent.graph import InboxGraph
    from app.agent.dispatcher import dispatch
    from app.contracts import ToolContext, ToolResult
    from app.privacy.redact import pii_map_for

    with pytest.raises(NotImplementedError):
        CampusLLM()
    with pytest.raises(NotImplementedError):
        GmailAPIClient()
    with pytest.raises(NotImplementedError):
        MockGmailAPIClient()
    with pytest.raises(NotImplementedError):
        InboxGraph()

    ctx = ToolContext(
        batch_id="b1", pii_map=pii_map_for("b1"), allowed_tools={"scan_emails"}
    )
    # with pytest.raises(NotImplementedError):
    #     dispatch("scan_emails", {}, ctx)