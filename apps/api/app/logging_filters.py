"""Logging filters that prevent privacy-sensitive data from reaching log sinks.

Attached to the root logger AND to every handler currently registered on it,
so it scrubs records emitted by application code, uvicorn, and any third
party that logs via the stdlib logging module.

NOTE: filters attached to a logger only run on records logged DIRECTLY to
that logger; they do not run on records propagated from children. Therefore
we attach to handlers as well, since handlers run filters on every record
that reaches them regardless of origin.
"""
from __future__ import annotations

import logging
import re

# Anything that mentions the redaction map by name.
_REDACTION_MAP_PATTERN = re.compile(r"redaction[_\-]?map", re.IGNORECASE)

# Mapping-shaped substrings: "[CATEGORY_N]" : "value"  or  [CATEGORY_N] = value
_MAP_ENTRY_PATTERN = re.compile(
    r"""\[[A-Z][A-Z0-9_]+_\d+\]\s*[:=]""",
)

_REDACTED_NOTICE = "[REDACTED: log line scrubbed by RedactionMapFilter]"


class RedactionMapFilter(logging.Filter):
    """Drop the message body of any log record that mentions redaction-map material.

    Returns True (record is kept) so the structural metadata still flows to
    sinks for observability, but the message text is replaced.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _REDACTION_MAP_PATTERN.search(msg) or _MAP_ENTRY_PATTERN.search(msg):
            record.msg = _REDACTED_NOTICE
            record.args = ()
        return True


def install_redaction_map_filter() -> RedactionMapFilter:
    """Install the filter on the root logger and all its current handlers.

    Idempotent: re-installing replaces any prior instance attached by this
    module so test setup/teardown works predictably.
    """
    f = RedactionMapFilter()
    root = logging.getLogger()

    # Remove any prior instance attached by this module.
    root.filters = [x for x in root.filters if not isinstance(x, RedactionMapFilter)]
    root.addFilter(f)

    for handler in root.handlers:
        handler.filters = [
            x for x in handler.filters if not isinstance(x, RedactionMapFilter)
        ]
        handler.addFilter(f)

    return f
