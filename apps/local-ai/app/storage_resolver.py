"""Secure storage-key resolver for the local-ai service.

The api / worker passes opaque storage *keys* (e.g.
``sessions/<uuid>/audio.wav``). This module turns a key into a real file
path on the read-only ``/data/storage`` mount, enforcing:

* keys must be relative
* no ``..`` segments
* must live under ``sessions/<uuid>/``
* resolved path must remain inside the storage root

Errors are raised as :class:`StorageKeyError` (invalid input) and
:class:`StorageNotFoundError` (well-formed but missing). The endpoint layer
maps these to HTTP 400 / 404 with **generic** messages so we never echo a
client-supplied path back to the caller.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.config import settings

# UUID v4 canonical form; we accept any UUID-shaped 8-4-4-4-12 hex (the
# api uses uuid.uuid4() but we don't need to enforce the version nibble).
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class StorageKeyError(ValueError):
    """The supplied key is not a valid sessions/<uuid>/... path."""


class StorageNotFoundError(LookupError):
    """The key is well-formed but no file exists at the resolved location."""


def _validate_key_shape(key: str) -> tuple[str, str]:
    """Return (session_id, remainder) or raise StorageKeyError.

    The check is performed on the raw string BEFORE filesystem resolution so
    we can reject malicious inputs without touching disk.
    """
    if not isinstance(key, str) or not key:
        raise StorageKeyError("empty key")

    # Reject Windows-style and POSIX absolute paths.
    if key.startswith(("/", "\\")):
        raise StorageKeyError("absolute path not allowed")
    # Reject drive letters like "C:..." even though we run on Linux in prod;
    # belt-and-braces for tests / dev on Windows hosts.
    if len(key) >= 2 and key[1] == ":":
        raise StorageKeyError("absolute path not allowed")

    # Normalize separators to POSIX for the syntactic checks. We do NOT use
    # os.path.normpath because that would silently collapse ".." segments.
    posix = key.replace("\\", "/")

    # Reject any "." or ".." segment, leading / trailing slashes, or doubles.
    parts = posix.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise StorageKeyError("invalid path segment")

    if parts[0] != "sessions":
        raise StorageKeyError("key must start with sessions/")
    if len(parts) < 3:
        raise StorageKeyError("key must reference a file under sessions/<uuid>/")
    session_id = parts[1]
    if not _UUID_RE.match(session_id):
        raise StorageKeyError("invalid session id")

    remainder = "/".join(parts[2:])
    return session_id, remainder


def resolve_storage_key(key: str, *, root: Path | None = None) -> Path:
    """Validate *key* and return an absolute, resolved Path inside the storage root.

    Raises :class:`StorageKeyError` for malformed / unsafe keys and
    :class:`StorageNotFoundError` if the file does not exist.
    """
    _validate_key_shape(key)

    storage_root = (root if root is not None else Path(settings.storage_root)).resolve()

    # Build the candidate path using a PurePosixPath to avoid any OS-specific
    # surprises; then materialize through Path for resolve().
    rel = PurePosixPath(key.replace("\\", "/"))
    candidate = (storage_root / Path(*rel.parts)).resolve()

    # Belt-and-braces check: even after syntactic validation, ensure the
    # resolved path is inside the root. Uses is_relative_to (Py >= 3.9).
    try:
        candidate.relative_to(storage_root)
    except ValueError as exc:
        raise StorageKeyError("path escapes storage root") from exc

    if not candidate.exists() or not candidate.is_file():
        raise StorageNotFoundError("file not found for key")

    return candidate
