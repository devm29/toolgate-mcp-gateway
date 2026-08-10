from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from toolgate.db import Base, utcnow


class Transport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class UpstreamStatus(StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class ToolStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class ChangeKind(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    REMOVED = "removed"


class ChangeResolution(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], native_enum=False, length=32)


class Upstream(Base):
    __tablename__ = "upstreams"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(48), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    transport: Mapped[Transport] = mapped_column(_enum(Transport, "transport"))
    command: Mapped[str | None] = mapped_column(Text)
    args: Mapped[list[str]] = mapped_column(JSONB, default=list)
    env: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    cwd: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[UpstreamStatus] = mapped_column(
        _enum(UpstreamStatus, "upstream_status"), default=UpstreamStatus.PENDING
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tools: Mapped[list[Tool]] = relationship(back_populates="upstream", cascade="all, delete-orphan")


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("upstream_id", "upstream_tool_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    upstream_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upstreams.id", ondelete="CASCADE"), index=True)
    upstream_tool_name: Mapped[str] = mapped_column(String(256))
    exposed_name: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[ToolStatus] = mapped_column(_enum(ToolStatus, "tool_status"), default=ToolStatus.PENDING, index=True)
    current_hash: Mapped[str] = mapped_column(String(64))
    current_definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_definition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="none")
    scan_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(160))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    upstream: Mapped[Upstream] = relationship(back_populates="tools")

    @property
    def is_servable(self) -> bool:
        return (
            self.status is ToolStatus.APPROVED
            and self.removed_at is None
            and self.approved_hash is not None
            and self.approved_hash == self.current_hash
        )


class ToolPin(Base):
    __tablename__ = "tool_pins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    approved_by: Mapped[str] = mapped_column(String(160))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolChange(Base):
    __tablename__ = "tool_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ChangeKind] = mapped_column(_enum(ChangeKind, "change_kind"))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    new_hash: Mapped[str] = mapped_column(String(64))
    previous_definition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[ChangeResolution | None] = mapped_column(_enum(ChangeResolution, "change_resolution"))
    resolved_by: Mapped[str | None] = mapped_column(String(160))
