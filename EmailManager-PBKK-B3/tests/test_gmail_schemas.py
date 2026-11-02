"""Tes skema tool Gmail (kontrak 2)."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.gmail import schemas
from app.gmail.schemas import (
    ArchiveThreadArgs,
    CreateDraftReplyArgs,
    FetchThreadArgs,
    LabelThreadArgs,
    ScanEmailsArgs,
)
from app.gmail.tools import ALL_TOOLS_MVP

ARGS_MODELS = [ScanEmailsArgs, FetchThreadArgs, LabelThreadArgs,
               ArchiveThreadArgs, CreateDraftReplyArgs]
LABEL_OK = {"thread_id": "t001", "category": "Tugas", "priority": "Mendesak", "reason": "tenggat Jumat"}


def test_tidak_ada_tool_kirim_email():
    assert not any("send" in name.lower() for name in dir(schemas))
    assert not any("send" in name for name in ALL_TOOLS_MVP)


def test_mvp_lima_tool_tanpa_trash():
    assert ALL_TOOLS_MVP == {"scan_emails", "fetch_thread", "label_thread",
                             "archive_thread", "create_draft_reply"}


def test_draft_menolak_penerima_dan_subjek_dari_llm():
    with pytest.raises(ValidationError):
        CreateDraftReplyArgs(thread_id="t001", body="Halo", to_email="x@evil.com")
    with pytest.raises(ValidationError):
        CreateDraftReplyArgs(thread_id="t001", body="Halo", subject="Re: lain")
    with pytest.raises(ValidationError):
        CreateDraftReplyArgs(thread_id="t001", body="")


def test_default_scan_emails():
    args = ScanEmailsArgs()
    assert (args.unread_only, args.newer_than_days, args.in_inbox, args.max_results) == (True, 7, True, 10)


@pytest.mark.parametrize("kwargs", [
    {"max_results": 0}, {"max_results": 51},
    {"newer_than_days": 0}, {"newer_than_days": 91},
])
def test_scan_emails_batas(kwargs):
    with pytest.raises(ValidationError):
        ScanEmailsArgs(**kwargs)


@pytest.mark.parametrize("domain", ["x.com OR in:trash", "univ.ac.id -label:x", "a b.com", "{x}.com"])
def test_sender_domain_menolak_operator_query(domain):
    with pytest.raises(ValidationError):
        ScanEmailsArgs(sender_domain=domain)


@pytest.mark.parametrize("domain", ["", "univ.ac.id", "mail.its.ac.id"])
def test_sender_domain_valid(domain):
    assert ScanEmailsArgs(sender_domain=domain).sender_domain == domain


def test_fetch_thread_batas_dan_thread_id():
    with pytest.raises(ValidationError):
        FetchThreadArgs(thread_id="t001", max_messages=21)
    with pytest.raises(ValidationError):
        FetchThreadArgs(thread_id="t001 OR x")
    assert FetchThreadArgs(thread_id="18c5e2a91f4b802a").max_messages == 5


def test_label_thread_enum_dan_reason():
    assert LabelThreadArgs(**LABEL_OK).category == "Tugas"
    with pytest.raises(ValidationError):
        LabelThreadArgs(**{**LABEL_OK, "category": "Penting"})
    with pytest.raises(ValidationError):
        LabelThreadArgs(**{**LABEL_OK, "priority": "Urgent"})
    with pytest.raises(ValidationError):
        LabelThreadArgs(**{**LABEL_OK, "reason": "x" * 201})


def test_promosi_selalu_nanti():
    with pytest.raises(ValidationError):
        LabelThreadArgs(**{**LABEL_OK, "category": "Promosi", "priority": "Normal"})
    assert LabelThreadArgs(**{**LABEL_OK, "category": "Spam", "priority": "Nanti"}).priority == "Nanti"


def test_skema_tanpa_anyof():
    dumped = json.dumps([m.model_json_schema() for m in ARGS_MODELS])
    assert "anyOf" not in dumped
