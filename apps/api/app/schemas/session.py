"""Pydantic schemas for the Session resource and its status transitions."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer
from app.schemas.guide import Guide as GuideContent

SourceType = Literal["recorded", "uploaded"]
SessionStatus = Literal["created", "uploaded", "processing", "ready", "failed"]

# Status transitions allowed by the system. Any other transition is rejected.
ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    "created": {"uploaded", "failed"},
    "uploaded": {"processing", "failed"},
    "processing": {"ready", "failed"},
    "ready": {"processing"},  # via /reprocess (force re-run)
    "failed": {"processing"},  # via /retry or /reprocess
}


def is_transition_allowed(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())  # type: ignore[arg-type]


class SessionCreate(BaseModel):
    title: str | None = None
    source_type: SourceType


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    status: SessionStatus
    progress_message: str | None = None
    source_type: SourceType
    media_key: str | None = None
    media_mime: str | None = None
    media_duration_sec: float | None = None
    media_size_bytes: int | None = None
    pipeline_artifacts: dict[str, Any] = Field(default_factory=dict)
    pipeline_events: list[dict[str, Any]] = Field(default_factory=list)
    ai_usage: dict[str, Any] = Field(default_factory=dict)
    guide_content: dict[str, Any] | None = None
    guide_schema_version: str | None = None
    guide_edited_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("pipeline_artifacts")
    def _filter_pipeline_artifacts(
        self, value: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Apply the public-artifacts allowlist before serialization.

        See `app.pipeline.common.public_artifacts` for the allowlist policy.
        This guarantees the API surface never returns raw OCR text, raw UI
        summaries, or any redaction-map material even if a stage writes them
        to the JSONB column.

        Imported lazily because `app.pipeline.common` imports
        `app.services.session_service`, which imports this schema module.
        """
        from app.pipeline.common import public_artifacts

        return public_artifacts(value)


class SessionGuideUpdate(BaseModel):
    guide: GuideContent
