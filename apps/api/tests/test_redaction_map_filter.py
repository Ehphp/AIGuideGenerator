"""Phase A: RedactionMapFilter scrubs log records that mention redaction-map material."""
from __future__ import annotations

import io
import logging

import pytest

from app.logging_filters import RedactionMapFilter, install_redaction_map_filter


@pytest.fixture()
def captured_logger():
    """A throwaway logger with a StringIO StreamHandler and the filter installed."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactionMapFilter())

    log = logging.getLogger("test.redaction_map_filter")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    try:
        yield log, buf
    finally:
        log.handlers.clear()


def test_filter_scrubs_records_mentioning_redaction_map_by_name(captured_logger):
    log, buf = captured_logger
    log.info("loaded redaction_map.local from disk: 12 entries")
    out = buf.getvalue()
    assert "redaction_map" not in out
    assert "REDACTED" in out


def test_filter_scrubs_records_with_mapping_shape(captured_logger):
    log, buf = captured_logger
    log.info('mapping entry: [EMAIL_1] : "user@example.com"')
    out = buf.getvalue()
    assert "user@example.com" not in out
    assert "EMAIL_1" not in out
    assert "REDACTED" in out


def test_filter_passes_benign_records(captured_logger):
    log, buf = captured_logger
    log.info("processed 4 events from build_timeline")
    out = buf.getvalue()
    assert "REDACTED" not in out
    assert "build_timeline" in out


def test_filter_handles_args_safely(captured_logger):
    log, buf = captured_logger
    # Use lazy formatting; record.getMessage() must still find the offending text.
    log.info("loaded %s entries", "redaction_map.local file")
    out = buf.getvalue()
    assert "redaction_map" not in out


def test_install_is_idempotent_on_root_logger():
    install_redaction_map_filter()
    install_redaction_map_filter()
    root = logging.getLogger()
    instances = [f for f in root.filters if isinstance(f, RedactionMapFilter)]
    assert len(instances) == 1


def test_install_attaches_filter_to_existing_handlers():
    root = logging.getLogger()
    # Snapshot existing handlers
    existing = list(root.handlers)
    extra = logging.StreamHandler(io.StringIO())
    root.addHandler(extra)
    try:
        install_redaction_map_filter()
        for handler in root.handlers:
            instances = [
                f for f in handler.filters if isinstance(f, RedactionMapFilter)
            ]
            assert len(instances) == 1, (
                f"handler {handler!r} expected exactly 1 RedactionMapFilter"
            )
    finally:
        root.removeHandler(extra)
        # Leave the prior handler set intact for downstream tests.
        for h in root.handlers:
            if h not in existing and h is not extra:
                root.removeHandler(h)


def test_filter_does_not_match_substring_redact_only():
    # We only match the explicit phrase; "redaction" alone (e.g. in product
    # copy) should not trigger. Confirm the regex requires the "_map" or "-map"
    # suffix.
    f = RedactionMapFilter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="redaction policy applied",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert record.getMessage() == "redaction policy applied"
