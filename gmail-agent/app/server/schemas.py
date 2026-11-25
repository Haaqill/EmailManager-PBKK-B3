"""Skema request dan response server agen."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchFilters(_RequestModel):
    max_results: StrictInt = Field(default=10, ge=1, le=10)


class StartBatchRequest(_RequestModel):
    filters: BatchFilters = Field(default_factory=BatchFilters)


class ExecuteDecision(_RequestModel):
    item_id: str = Field(min_length=1)
    decision: Literal["approve", "reject"]
    edited_draft_body: str | None = Field(default=None, max_length=10_000)
    confirmed_trash: StrictBool | None = None


class ExecuteBatchRequest(_RequestModel):
    plan_version: StrictInt = Field(ge=1)
    decisions: list[ExecuteDecision]


class AuthStatusResponse(BaseModel):
    status: Literal["connected", "not_connected", "expired"]


class BeginLoginResponse(BaseModel):
    auth_url: str
