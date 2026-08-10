from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from toolgate.registry.models import ChangeKind, ChangeResolution, ToolStatus, Transport, UpstreamStatus
from toolgate.registry.naming import SEPARATOR, UPSTREAM_NAME
from toolgate.scanner.models import Finding, RiskLevel, ScanReport

REDACTED = "••••••"


class UpstreamFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    transport: Transport
    command: str | None = Field(default=None, max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: AnyHttpUrl | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _transport_requirements(self) -> UpstreamFields:
        if self.transport is Transport.STDIO and not self.command:
            raise ValueError("stdio upstreams need a command")
        if self.transport is Transport.STREAMABLE_HTTP and self.url is None:
            raise ValueError("streamable_http upstreams need a url")
        return self


class UpstreamCreate(UpstreamFields):
    name: str = Field(description="Namespace prefix for exposed tools, e.g. 'github' -> github__create_issue")

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not UPSTREAM_NAME.match(value) or SEPARATOR in value:
            raise ValueError("use 2-32 lowercase letters, digits or single dashes, starting with a letter")
        return value


class UpstreamUpdate(BaseModel):
    """PATCH body. Omitted fields keep their stored value; env and header values may be the redacted placeholder."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    transport: Transport | None = None
    command: str | None = Field(default=None, max_length=1000)
    args: list[str] | None = Field(default=None, max_length=64)
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: AnyHttpUrl | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _no_null_required(self) -> UpstreamUpdate:
        for name in ("display_name", "description", "transport", "args", "enabled"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ToolCounts(BaseModel):
    total: int = 0
    approved: int = 0
    pending: int = 0
    quarantined: int = 0
    rejected: int = 0


class UpstreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    transport: Transport
    command: str | None
    args: list[str]
    env: dict[str, str]
    cwd: str | None
    url: str | None
    headers: dict[str, str]
    enabled: bool
    status: UpstreamStatus
    last_error: str | None
    last_synced_at: datetime | None
    created_at: datetime
    tool_counts: ToolCounts = Field(default_factory=ToolCounts)
    max_risk_score: int = 0

    @field_validator("env", "headers", mode="after")
    @classmethod
    def _redact(cls, value: dict[str, str]) -> dict[str, str]:
        return dict.fromkeys(value, REDACTED)


class ToolSummary(BaseModel):
    id: uuid.UUID
    exposed_name: str
    upstream_id: uuid.UUID
    upstream_name: str
    upstream_tool_name: str
    title: str | None
    description: str
    status: ToolStatus
    risk_score: int
    risk_level: RiskLevel
    finding_count: int
    has_drift: bool
    removed: bool
    first_seen_at: datetime
    last_seen_at: datetime
    status_changed_at: datetime
    approved_at: datetime | None
    approved_by: str | None


class PinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha256: str
    approved_by: str
    note: str
    created_at: datetime


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ChangeKind
    previous_hash: str | None
    new_hash: str
    detected_at: datetime
    resolved_at: datetime | None
    resolution: ChangeResolution | None
    resolved_by: str | None


class ToolDetail(ToolSummary):
    current_hash: str
    approved_hash: str | None
    current_definition: dict[str, Any]
    approved_definition: dict[str, Any] | None
    scan_report: ScanReport | None
    pins: list[PinOut]
    changes: list[ChangeOut]


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Hash of the definition the reviewer looked at; approval fails if the tool changed since",
    )
    note: str = Field(default="", max_length=500)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)


class ApprovalItem(BaseModel):
    tool: ToolSummary
    change: ChangeOut | None
    top_findings: list[Finding]


class SyncResult(BaseModel):
    upstream: str
    discovered: int = 0
    new: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    quarantined: list[str] = Field(default_factory=list)
    restored: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    auto_approved: list[str] = Field(default_factory=list)


class ToolFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ToolStatus | None = None
    upstream_id: uuid.UUID | None = None
    risk: RiskLevel | None = None
    q: str | None = Field(default=None, max_length=100)
    include_removed: bool = False
