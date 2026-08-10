from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Decision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    QUARANTINED = "quarantined"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_TOOL = "unknown_tool"
    UPSTREAM_ERROR = "upstream_error"

    @property
    def blocked(self) -> bool:
        return self in {Decision.DENIED, Decision.QUARANTINED, Decision.RATE_LIMITED, Decision.UNKNOWN_TOOL}


class AuditEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime | None = None
    request_id: str
    principal: str
    client_id: str | None = None
    tool_name: str
    upstream: str | None = None
    upstream_tool: str | None = None
    decision: Decision
    reason: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    is_error: bool = False
    trace_id: str | None = None
    span_id: str | None = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    request_id: str
    principal: str
    client_id: str | None
    tool_name: str
    upstream: str | None
    upstream_tool: str | None
    decision: Decision
    reason: str
    arguments: dict[str, Any]
    latency_ms: float
    is_error: bool
    trace_id: str | None


class AuditFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision | None = None
    tool: str | None = Field(default=None, max_length=160)
    principal: str | None = Field(default=None, max_length=160)
    upstream: str | None = Field(default=None, max_length=48)


class HourlyBucket(BaseModel):
    hour: datetime
    allowed: int = 0
    blocked: int = 0
    errors: int = 0


class ToolUsage(BaseModel):
    tool_name: str
    calls: int
    blocked: int


class AuditStats(BaseModel):
    window_hours: int
    total: int
    allowed: int
    blocked: int
    errors: int
    p95_latency_ms: float
    by_decision: dict[Decision, int]
    hourly: list[HourlyBucket]
    top_tools: list[ToolUsage]
