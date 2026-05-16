"""Pure unit tests for status-transition rules (no DB)."""
from __future__ import annotations

import pytest

from app.schemas.session import is_transition_allowed


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ("created", "uploaded", True),
        ("created", "ready", False),
        ("uploaded", "processing", True),
        ("uploaded", "ready", False),
        ("processing", "ready", True),
        ("processing", "failed", True),
        ("ready", "processing", True),  # via /reprocess (force re-run)
        ("failed", "processing", True),
        ("failed", "ready", False),
        ("processing", "processing", True),  # same-state allowed (idempotent)
    ],
)
def test_status_transitions(current: str, target: str, expected: bool) -> None:
    assert is_transition_allowed(current, target) is expected
