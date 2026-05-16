"""Safety guardrails for the privacy boundary (Phase A).

This module provides the runtime checks that prevent stages talking to
external AI providers from accidentally consuming raw / unsanitized data.

Two complementary mechanisms:

1. **Forbidden artifact keys**: stages that send data outside the host MUST
   read artifacts via :func:`read_public_artifact_for_llm`, which refuses
   any key in :data:`FORBIDDEN_ARTIFACT_KEYS_FOR_LLM`.

2. **Detector smoke test**: :func:`assert_not_raw_artifact` walks any
   JSON-ish payload and raises :class:`RawDataLeakError` on obvious PII
   hits. Phase A ships a minimal detector set; Phase E will re-route this
   function through the full sanitizer detector catalog.

Errors are intentionally vague — the exception message MUST NOT echo the
offending value, the artifact contents, or any redaction-map material.
"""
from __future__ import annotations

import json
import re
from typing import Any


class RawDataLeakError(RuntimeError):
    """Raised when a guardrail detects raw data crossing an external boundary.

    The message is intentionally minimal (category + stage label only) so
    exception logging and HTTP error responses cannot leak sensitive content.
    """


# Artifact keys that must NEVER be loaded by code that talks to an external
# AI provider. These contain raw transcripts, raw OCR output, raw merged
# timelines, or the local-only redaction map.
FORBIDDEN_ARTIFACT_KEYS_FOR_LLM: frozenset[str] = frozenset(
    {
        "transcribe",
        "transcribe_local",
        "ocr_frames",
        "ocr_frames_local",
        "build_raw_timeline",
        "raw_timeline",
        "redaction_map.local",
        "redaction_map",
    }
)


def read_public_artifact_for_llm(session_id, stage: str) -> Any | None:
    """Read an artifact for a stage that will send data to an external LLM.

    Refuses any stage in :data:`FORBIDDEN_ARTIFACT_KEYS_FOR_LLM`.
    Use :func:`app.pipeline.common.read_artifact` directly for purely local
    consumers (e.g. the rehydrator).
    """
    if stage in FORBIDDEN_ARTIFACT_KEYS_FOR_LLM:
        raise RawDataLeakError(
            f"forbidden artifact for external LLM: stage={stage!r}"
        )
    # Late import to avoid a circular dependency between common.py and
    # safety.py (common.py is imported by every stage).
    from app.pipeline import common

    return common.read_artifact(session_id, stage)


# ---------------------------------------------------------------------------
# Phase A baseline detector set.
#
# This is intentionally small. Phase E will replace this list with a delegate
# that calls into ``app.sanitize.categories`` so the same detector catalog
# powers both sanitization and the leak-tripwire.
# ---------------------------------------------------------------------------
_DETECTOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    (
        "API_KEY",
        re.compile(r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    ),
    # Conservative PASSWORD smoke-test: keyword + separator + non-trivial value.
    # This is a belt-and-suspenders guard; the primary redaction happens in the
    # sanitize_timeline stage via the full PASSWORD detector in categories.py.
    # Note: intentionally simpler than the primary detector (no lookbehind, no
    # value_group) — it only needs to raise an alarm, not produce clean output.
    (
        "PASSWORD",
        re.compile(
            r'\b(?:password|passwd|passcode|pwd|secret)\b["\']?\s*[=:]\s*["\']?(?!\[)[^\s"\'\r\n]{4,}',
            re.IGNORECASE,
        ),
    ),
)


def _coerce_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            return payload.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive
            return ""
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(payload)


def prepare_for_egress(timeline: dict[str, Any], *, context: str = "egress") -> dict[str, Any]:
    """Return a sanitized-for-egress copy of a timeline payload.

    Two operations are applied before any external LLM call:

    1. **Frame-key opacification**: ``frame_key`` values contain the session
       UUID embedded in the storage path
       (``sessions/<uuid>/frames/frame_0007.jpg``).  This UUID is an internal
       identifier that has no value for the model but is an unnecessary
       correlation handle.  We replace it with just the filename stem
       (``frame_0007``) so the model still understands which frame is being
       referenced without the session identifier crossing the boundary.

    2. **PII smoke-test**: calls :func:`assert_not_raw_artifact` on the prepared
       payload as a belt-and-braces check that the sanitizer did its job.

    Returns a deep copy — the original ``timeline`` is never mutated.
    """
    import copy

    prepared: dict[str, Any] = copy.deepcopy(timeline)
    events = prepared.get("events") or []
    for event in events:
        if not isinstance(event, dict):
            continue
        key = event.get("frame_key")
        if key and isinstance(key, str):
            # Keep only the filename stem:
            # "sessions/<uuid>/frames/frame_0007.jpg" → "frame_0007"
            stem = key.replace("\\", "/").split("/")[-1]
            stem = stem.rsplit(".", 1)[0]
            event["frame_key"] = stem
    assert_not_raw_artifact(prepared, context=context)
    return prepared


def assert_not_raw_artifact(payload: Any, *, context: str = "external") -> None:
    """Smoke-test a payload before sending it across an external boundary.

    Raises :class:`RawDataLeakError` if a known PII pattern is found.
    The exception message contains only the category and a context label;
    it never echoes the offending substring.
    """
    text = _coerce_text(payload)
    if not text:
        return
    for category, pattern in _DETECTOR_PATTERNS:
        if pattern.search(text):
            raise RawDataLeakError(
                f"raw data leak detected: category={category} context={context}"
            )
