from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolgate.db import Base, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_tool_occurred", "tool_name", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    request_id: Mapped[str] = mapped_column(String(64))
    principal: Mapped[str] = mapped_column(String(160), index=True)
    client_id: Mapped[str | None] = mapped_column(String(96))
    tool_name: Mapped[str] = mapped_column(String(160))
    upstream: Mapped[str | None] = mapped_column(String(48))
    upstream_tool: Mapped[str | None] = mapped_column(String(256))
    decision: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    span_id: Mapped[str | None] = mapped_column(String(16))
