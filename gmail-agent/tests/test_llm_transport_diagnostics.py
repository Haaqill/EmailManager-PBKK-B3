"""Safe metadata diagnostics for the campus LLM transport."""
from __future__ import annotations

import logging

import pytest

from app.config import LLMConfig
from app.llm.transport import LLMHTTPError, send_chat_request
from tests.fake_openai_server import FakeOpenAI


TOOLS = [{"type": "function", "function": {"name": "submit_classification", "parameters": {}}}]


def _config(base_url: str) -> LLMConfig:
    return LLMConfig(base_url=base_url, api_key="test-secret-key", model="test-model")


def test_request_and_response_logs_contain_only_tool_metadata(caplog):
    caplog.set_level(logging.INFO, logger="gmail_agent.llm.transport")
    with FakeOpenAI("tools_ok", api_key="test-secret-key") as fake:
        send_chat_request(
            _config(fake.base_url),
            [{"role": "user", "content": "private email body"}],
            tools=TOOLS,
            tool_choice={"type": "function", "function": {"name": "submit_classification"}},
        )

    assert fake.requests[0]["tool_choice"] == {
        "type": "function", "function": {"name": "submit_classification"}
    }

    request = next(record for record in caplog.records if record.message == "llm request metadata")
    response = next(record for record in caplog.records if record.message == "llm response metadata")
    assert request.tool_names == ["submit_classification"]
    assert request.forced_tool == "submit_classification"
    assert response.finish_reason == "stop"
    assert response.has_tool_calls is True
    assert response.response_tool_names == ["label_email"]
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "private email body" not in rendered
    assert "test-secret-key" not in rendered


def test_http_error_log_has_safe_classification_without_raw_response(caplog):
    caplog.set_level(logging.WARNING, logger="gmail_agent.llm.transport")
    with FakeOpenAI("reject_tools", api_key="test-secret-key") as fake:
        with pytest.raises(LLMHTTPError, match="gateway_error=tools_unsupported"):
            send_chat_request(_config(fake.base_url), [], tools=TOOLS)

    record = next(record for record in caplog.records if record.message == "llm HTTP error metadata")
    assert record.http_status == 400
    assert record.gateway_error_kind == "tools_unsupported"
    assert "not supported" not in record.getMessage()
    assert "test-secret-key" not in record.getMessage()
