"""Session ORM model — see plan §4."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Valid status values. Transitions enforced in the service layer.
SESSION_STATUSES = ("created", "uploaded", "processing", "ready", "failed")
SOURCE_TYPES = ("recorded", "uploaded")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    media_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    pipeline_artifacts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    pipeline_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    ai_usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    guide_content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    guide_schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    guide_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
