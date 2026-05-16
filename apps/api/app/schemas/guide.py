"""Pydantic schema for the generated Guide v1.0."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

GUIDE_SCHEMA_VERSION = "1.0"


class Action(BaseModel):
    verb: str
    target: str
    value: Optional[str] = None


class Evidence(BaseModel):
    frame_keys: list[str] = Field(default_factory=list)
    transcript_excerpt: str = ""
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    # Provenance fields set by the deterministic attach_evidence stage.
    # None on guides generated before this feature was introduced.
    frame_source: Optional[str] = None   # "llm" | "nearest_frame" | "none"
    frame_distance_sec: Optional[float] = None


class Step(BaseModel):
    id: str
    order: int
    title: str
    description: str
    actions: list[Action] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class Troubleshooting(BaseModel):
    symptom: str
    likely_cause: str
    resolution: str


class GuideMetadata(BaseModel):
    generated_by: str = ""
    generated_at: str = ""
    source_session_id: str = ""
    source_duration_sec: Optional[float] = None


class Guide(BaseModel):
    schema_version: str = GUIDE_SCHEMA_VERSION
    title: str
    summary: str
    estimated_duration_minutes: Optional[float] = None
    prerequisites: list[str] = Field(default_factory=list)
    tools_or_systems: list[str] = Field(default_factory=list)
    steps: list[Step]
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    troubleshooting: list[Troubleshooting] = Field(default_factory=list)
    metadata: GuideMetadata = Field(default_factory=GuideMetadata)
