"""Storage backend interface.

The contract is intentionally small so a future S3 implementation is a drop-in.
Keys are forward-slash-separated relative paths; backends decide where they live.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path


class StorageBackend(ABC):
    @abstractmethod
    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> int:
        """Persist the given async byte stream under `key`. Returns total bytes written."""

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Return the local filesystem path for `key`. Used by ffmpeg/ffprobe.

        For non-local backends this would download to a temp file first.
        """

    @abstractmethod
    async def open_bytes(self, key: str) -> AsyncIterator[bytes]:
        """Yield the bytes of the object stored under `key`."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        """Delete all keys under the given prefix (e.g. an entire session folder)."""
