"""Phase B: storage_resolver enforces a strict allowlist on storage keys."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.storage_resolver import (
    StorageKeyError,
    StorageNotFoundError,
    resolve_storage_key,
)


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def session_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def existing_audio(storage_root: Path, session_id: str) -> tuple[str, Path]:
    sess_dir = storage_root / "sessions" / session_id
    sess_dir.mkdir(parents=True)
    audio = sess_dir / "audio.wav"
    audio.write_bytes(b"RIFF")
    return f"sessions/{session_id}/audio.wav", audio


@pytest.fixture()
def existing_frame(storage_root: Path, session_id: str) -> tuple[str, Path]:
    frames = storage_root / "sessions" / session_id / "frames"
    frames.mkdir(parents=True)
    img = frames / "frame_0001.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    return f"sessions/{session_id}/frames/frame_0001.jpg", img


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_resolves_audio_key(storage_root, existing_audio):
    key, expected = existing_audio
    resolved = resolve_storage_key(key, root=storage_root)
    assert resolved == expected.resolve()


def test_resolves_frame_key(storage_root, existing_frame):
    key, expected = existing_frame
    resolved = resolve_storage_key(key, root=storage_root)
    assert resolved == expected.resolve()


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_rejects_empty_key(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("", root=storage_root)


def test_rejects_absolute_posix_path(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("/etc/passwd", root=storage_root)


def test_rejects_absolute_windows_path(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("C:\\Windows\\System32\\config\\sam", root=storage_root)


def test_rejects_backslash_root(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("\\sessions\\foo", root=storage_root)


def test_rejects_double_dot_segment(storage_root, session_id):
    with pytest.raises(StorageKeyError):
        resolve_storage_key(
            f"sessions/{session_id}/../etc/passwd", root=storage_root
        )


def test_rejects_double_dot_at_start(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("../sessions/x/audio.wav", root=storage_root)


def test_rejects_dot_segment(storage_root, session_id):
    with pytest.raises(StorageKeyError):
        resolve_storage_key(f"sessions/./{session_id}/audio.wav", root=storage_root)


def test_rejects_double_slash(storage_root, session_id):
    with pytest.raises(StorageKeyError):
        resolve_storage_key(f"sessions//{session_id}/audio.wav", root=storage_root)


def test_rejects_non_session_prefix(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("models/whisper.bin", root=storage_root)


def test_rejects_session_dir_only_no_file(storage_root, session_id):
    with pytest.raises(StorageKeyError):
        resolve_storage_key(f"sessions/{session_id}", root=storage_root)


def test_rejects_invalid_uuid(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key("sessions/not-a-uuid/audio.wav", root=storage_root)


def test_rejects_non_string(storage_root):
    with pytest.raises(StorageKeyError):
        resolve_storage_key(None, root=storage_root)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


def test_well_formed_but_missing_file_raises_not_found(storage_root, session_id):
    with pytest.raises(StorageNotFoundError):
        resolve_storage_key(
            f"sessions/{session_id}/audio.wav", root=storage_root
        )


def test_directory_is_not_a_file(storage_root, session_id):
    sess_dir = storage_root / "sessions" / session_id
    sess_dir.mkdir(parents=True)
    (sess_dir / "frames").mkdir()
    # The path resolves but is a directory, not a file.
    with pytest.raises(StorageNotFoundError):
        resolve_storage_key(f"sessions/{session_id}/frames", root=storage_root)


# ---------------------------------------------------------------------------
# Privacy: error messages must not echo the offending key
# ---------------------------------------------------------------------------


def test_error_messages_do_not_echo_input(storage_root):
    secret = "/var/secrets/api_key.txt"
    try:
        resolve_storage_key(secret, root=storage_root)
    except StorageKeyError as exc:
        assert secret not in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected StorageKeyError")
