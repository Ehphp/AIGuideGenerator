"""Deterministic, stateful sanitizer.

Given raw text or a raw timeline, produces:

- a sanitized copy where every detected sensitive value is replaced by a
  monotonically-numbered placeholder per category (`[EMAIL_1]`, `[EMAIL_2]`,
  `[IBAN_1]`, ...);
- a `redaction_map` mapping each placeholder back to its original value;
- a `report` of category → count for observability.

Placeholders are stable per `Sanitizer` instance: the same input value
produces the same placeholder across all calls. Use one `Sanitizer` per
session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.sanitize.categories import Detector, detect_all


PLACEHOLDER_PREFIX = "["
PLACEHOLDER_SUFFIX = "]"


def _normalize(det: Detector, value: str) -> str:
    if det.normalize == "lower":
        return value.lower()
    return value


@dataclass
class SanitizationResult:
    sanitized: dict[str, Any]
    redaction_map: dict[str, str]
    report: dict[str, Any] = field(default_factory=dict)


class Sanitizer:
    """Per-session sanitizer. Not thread-safe; one instance per timeline."""

    def __init__(self) -> None:
        # category → next index to assign.
        self._counters: dict[str, int] = {}
        # (category, normalized_value) → placeholder.
        self._value_to_placeholder: dict[tuple[str, str], str] = {}
        # placeholder → original value (last seen casing).
        self._placeholder_to_value: dict[str, str] = {}
        # category → number of REPLACEMENTS made (not distinct values).
        self._counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sanitize_text(self, text: str | None) -> str:
        if not text:
            return text or ""
        hits = detect_all(text)
        if not hits:
            return text
        out: list[str] = []
        cursor = 0
        for det, match in hits:
            if det.value_group is not None:
                # Replace only the named sub-group; the prefix (keyword label,
                # separator, quotes) and the suffix (closing quote) that are
                # part of the full match are preserved verbatim.
                #
                # Example with value_group="value":
                #   input:  password: Secret123!
                #   output: password: [PASSWORD_1]
                #
                # redaction_map contains the bare value, not the full match.
                out.append(text[cursor : match.start(det.value_group)])
                placeholder = self._placeholder_for(det, match.group(det.value_group))
                out.append(placeholder)
                # Emit any suffix chars between end of value_group and end of
                # the full match (e.g. the closing quote in `"secret123"`).
                out.append(text[match.end(det.value_group) : match.end()])
            else:
                # Original behaviour: replace the entire match span.
                out.append(text[cursor : match.start()])
                placeholder = self._placeholder_for(det, match.group(0))
                out.append(placeholder)
            cursor = match.end()
        out.append(text[cursor:])
        return "".join(out)

    def sanitize_timeline(self, timeline: dict[str, Any]) -> SanitizationResult:
        """Sanitize a `build_timeline` artifact in-place-style (no mutation).

        Recognised event fields containing free text: `text`, `ocr_text`,
        `ui_summary`. All other fields pass through untouched.
        """
        events_in = timeline.get("events") or []
        if not isinstance(events_in, list):
            events_in = []

        events_out: list[dict[str, Any]] = []
        for ev in events_in:
            if not isinstance(ev, dict):
                events_out.append(ev)
                continue
            new_ev: dict[str, Any] = {}
            for k, v in ev.items():
                if k in {"text", "ocr_text", "ui_summary"} and isinstance(v, str):
                    new_ev[k] = self.sanitize_text(v)
                else:
                    new_ev[k] = v
            events_out.append(new_ev)

        sanitized = {
            "language": timeline.get("language"),
            "events": events_out,
        }

        report = {
            "events_total": len(events_in),
            "events_modified": sum(
                1
                for orig, new in zip(events_in, events_out)
                if orig != new
            ),
            "placeholders_total": sum(self._counts.values()),
            "distinct_values": len(self._value_to_placeholder),
            "categories": dict(sorted(self._counts.items())),
        }

        return SanitizationResult(
            sanitized=sanitized,
            redaction_map=dict(self._placeholder_to_value),
            report=report,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _placeholder_for(self, det: Detector, value: str) -> str:
        key = (det.category, _normalize(det, value))
        ph = self._value_to_placeholder.get(key)
        if ph is None:
            n = self._counters.get(det.category, 0) + 1
            self._counters[det.category] = n
            ph = f"{PLACEHOLDER_PREFIX}{det.category}_{n}{PLACEHOLDER_SUFFIX}"
            self._value_to_placeholder[key] = ph
            self._placeholder_to_value[ph] = value
        self._counts[det.category] = self._counts.get(det.category, 0) + 1
        return ph
