"""Pydantic schema for the generated Guide.

Schema version history
----------------------
1.0 — Original procedural-only schema.  ``steps`` was a required field.
1.1 — Adaptive schema.  ``steps`` is now optional (default []).  Added
      ``document_type``, ``intended_audience``, and ``sections`` for
      non-procedural documentation.  Fully backward-compatible: old guides
      that have only ``steps`` continue to validate without change.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

GUIDE_SCHEMA_VERSION = "1.1"


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


class GuideSection(BaseModel):
    """A free-form section used by non-procedural document types.

    ``kind`` identifies the section type so renderers can apply appropriate
    formatting.  ``content`` holds the main prose.  ``items`` holds bullet
    points or enumerated entries.  ``steps`` holds procedural steps if this
    section happens to contain a procedure within a larger non-procedural doc.
    """

    kind: str = "notes"
    # e.g. "overview" | "procedure" | "technical" | "conceptual" |
    #      "diagnostic" | "demo" | "notes" | "references"
    title: str
    content: str = ""
    items: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GuideMetadata(BaseModel):
    generated_by: str = ""
    generated_at: str = ""
    source_session_id: str = ""
    source_duration_sec: Optional[float] = None


class Guide(BaseModel):
    schema_version: str = GUIDE_SCHEMA_VERSION
    # --- Adaptive fields (schema v1.1, all optional for backward compat) ---
    document_type: Optional[str] = None
    # e.g. "procedural" | "technical" | "conceptual" | "diagnostic" | "demo" | "mixed"
    intended_audience: Optional[str] = None
    # e.g. "end_user" | "developer" | "sysadmin" | "operator" | "mixed"
    sections: list[GuideSection] = Field(default_factory=list)
    # --- Core fields (present in all schema versions) ---
    title: str
    summary: str
    estimated_duration_minutes: Optional[float] = None
    prerequisites: list[str] = Field(default_factory=list)
    tools_or_systems: list[str] = Field(default_factory=list)
    # steps is now optional (default []) so non-procedural docs can omit it.
    # Old guides that always had steps continue to validate unchanged.
    steps: list[Step] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    troubleshooting: list[Troubleshooting] = Field(default_factory=list)
    metadata: GuideMetadata = Field(default_factory=GuideMetadata)
