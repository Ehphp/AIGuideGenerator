"""Local filesystem storage backend rooted at `STORAGE_DIR`."""
from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from app.config import settings
from app.storage.base import StorageBackend


class PathTraversalError(ValueError):
    pass


class LocalStorage(StorageBackend):
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Reject absolute keys and any key that escapes the storage root.
        if not key or key.startswith("/") or key.startswith("\\"):
            raise PathTraversalError(f"invalid key: {key!r}")
        candidate = (self.root / key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathTraversalError(f"key escapes storage root: {key!r}") from exc
        return candidate

    def local_path(self, key: str) -> Path:
        return self._resolve(key)

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except PathTraversalError:
            return False

    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> int:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        async with aiofiles.open(path, "wb") as f:
            async for chunk in stream:
                if not chunk:
                    continue
                await f.write(chunk)
                total += len(chunk)
        return total

    async def open_bytes(self, key: str) -> AsyncIterator[bytes]:
        path = self._resolve(key)
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    async def delete_prefix(self, prefix: str) -> None:
        path = self._resolve(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)


_default: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _default
    if _default is None:
        _default = LocalStorage()
    return _default
