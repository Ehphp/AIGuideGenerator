"""Rehydrate placeholders back to original values.

Walks any JSON-ish structure replacing `[CATEGORY_N]` tokens using the
local redaction map. Unknown placeholders are left untouched and counted
so callers can warn / audit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Matches `[ANY_UPPER_OR_DIGITS_1]`. Conservative on the inner shape so
# we don't accidentally rehydrate brackets used in normal prose.
_PLACEHOLDER_RE = re.compile(r"\[([A-Z][A-Z0-9_]{0,30}_\d+)\]")


@dataclass
class RehydrationStats:
    resolved: int = 0
    unresolved: int = 0
    unresolved_placeholders: list[str] = field(default_factory=list)


def rehydrate_text(text: str | None, redaction_map: dict[str, str]) -> tuple[str, RehydrationStats]:
    stats = RehydrationStats()
    if not text:
        return text or "", stats

    def _sub(m: re.Match[str]) -> str:
        token = f"[{m.group(1)}]"
        original = redaction_map.get(token)
        if original is None:
            stats.unresolved += 1
            if token not in stats.unresolved_placeholders:
                stats.unresolved_placeholders.append(token)
            return token
        stats.resolved += 1
        return original

    return _PLACEHOLDER_RE.sub(_sub, text), stats


def rehydrate_obj(value: Any, redaction_map: dict[str, str]) -> tuple[Any, RehydrationStats]:
    """Recursively rehydrate every string leaf in a JSON-ish structure."""
    stats = RehydrationStats()

    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            new, s = rehydrate_text(v, redaction_map)
            stats.resolved += s.resolved
            stats.unresolved += s.unresolved
            for ph in s.unresolved_placeholders:
                if ph not in stats.unresolved_placeholders:
                    stats.unresolved_placeholders.append(ph)
            return new
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        return v

    return _walk(value), stats
