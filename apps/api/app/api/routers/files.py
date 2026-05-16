"""Files router: serves arbitrary stored objects under STORAGE_DIR.

Phase 1: no auth (localhost-only constraint stated in README). Path-traversal
is rejected by the storage backend itself.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.storage.local import PathTraversalError, get_storage

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{key:path}")
async def get_file(key: str) -> StreamingResponse:
    storage = get_storage()
    try:
        path = storage.local_path(key)
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="invalid key")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return StreamingResponse(storage.open_bytes(key), media_type="application/octet-stream")
