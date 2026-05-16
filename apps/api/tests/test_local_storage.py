"""Path-traversal guard tests for LocalStorage."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.local import LocalStorage, PathTraversalError


def test_local_path_resolves_within_root(tmp_path: Path) -> None:
    s = LocalStorage(root=tmp_path)
    p = s.local_path("sessions/abc/original.webm")
    assert p == (tmp_path / "sessions/abc/original.webm").resolve()


@pytest.mark.parametrize(
    "key",
    [
        "../escape.txt",
        "sessions/../../etc/passwd",
        "/absolute/path",
        "\\absolute\\windows",
        "",
    ],
)
def test_local_path_rejects_traversal(tmp_path: Path, key: str) -> None:
    s = LocalStorage(root=tmp_path)
    with pytest.raises(PathTraversalError):
        s.local_path(key)
