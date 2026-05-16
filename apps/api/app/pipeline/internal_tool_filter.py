"""Deterministic filter for Guide Generator self-referential events.

The pipeline records screen captures from the moment the user starts
interacting with the Guide Generator app. The first few events in any
recording therefore often contain OCR / transcript text that describes
the Guide Generator UI itself (status badges, buttons, etc.) rather than
the target workflow.

This module identifies those events and trims the *continuous leading
prefix* of self-referential noise so that `sanitize_timeline.py` (and
ultimately the LLM prompt) never sees them.

Strategy
--------
An event is classified as noise when any entry in ``_STRONG_TERMS`` appears
in its text fields (case-insensitive). Generic words like "ready",
"processing", or "session" are intentionally absent from the list — they are
too common to use as noise signals on their own.

Only the **continuous leading prefix** of noise events is trimmed. Events
that appear after the first non-noise event are never touched, even if they
would individually match a strong term.

Public API
----------
    is_internal_tool_event(event)                  -> bool
    trim_internal_tool_prefix(events)              -> (kept, dropped)
    filter_internal_tool_noise_from_timeline(tl)   -> timeline dict
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Term list
# ---------------------------------------------------------------------------

# Each term is matched case-insensitively anywhere in the event text.
# Keep terms specific enough to avoid false positives on real procedures.
_STRONG_TERMS: list[str] = [
    "Guide Generator",
    "Download DOCX",
    "Edit guide",
    "Generate guide",
    "Upload video",
    "Start recording",
    "Stop recording",
    "Reprocess",
    "New session",
]

# Pre-compile patterns (case-insensitive whole-substring match).
_STRONG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(re.escape(t), re.IGNORECASE) for t in _STRONG_TERMS
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_text(event: dict[str, Any]) -> str:
    """Concatenate all text-carrying fields of a timeline event."""
    parts: list[str] = []
    for field in ("text", "ocr_text", "ui_summary"):
        val = event.get(field)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    return " ".join(parts)


def _has_strong(text: str) -> bool:
    return any(p.search(text) for p in _STRONG_PATTERNS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_internal_tool_event(event: dict[str, Any]) -> bool:
    """Return True if *event* looks like Guide Generator self-referential noise.

    A strong term match is required. Generic words such as "ready",
    "processing", or "session" are not sufficient on their own.
    """
    text = _event_text(event)
    if not text:
        return False
    return _has_strong(text)


def trim_internal_tool_prefix(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove the continuous leading block of internal-tool-noise events.

    Returns ``(kept, dropped)`` where *dropped* is the leading prefix that
    was removed. Events appearing after the first non-noise event are never
    touched, even if they would individually be classified as noise.

    Examples
    --------
    >>> events = [noise, noise, real, noise, real]
    >>> trim_internal_tool_prefix(events)
    ([real, noise, real], [noise, noise])
    """
    cut = 0
    for event in events:
        if is_internal_tool_event(event):
            cut += 1
        else:
            break
    return events[cut:], events[:cut]


def filter_internal_tool_noise_from_timeline(
    timeline: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of *timeline* with the leading noise prefix removed.

    The original timeline is never mutated. A ``"internal_tool_filter"``
    key is added to the returned dict with debug metadata:

    .. code-block:: json

        {
          "internal_tool_filter": {
            "dropped_prefix_events": 2
          }
        }

    If no events are dropped the key is still present with a count of 0.
    """
    events: list[dict[str, Any]] = list(timeline.get("events") or [])
    kept, dropped = trim_internal_tool_prefix(events)

    result = {**timeline, "events": kept}
    result["internal_tool_filter"] = {"dropped_prefix_events": len(dropped)}
    return result
