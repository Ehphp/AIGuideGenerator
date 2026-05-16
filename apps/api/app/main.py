"""FastAPI entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import files as files_router
from app.api.routers import sessions as sessions_router
from app.config import settings
from app.db import create_all
from app.logging_filters import install_redaction_map_filter

# Install the redaction-map log filter as early as possible so any subsequent
# logging from the FastAPI app or its dependencies is scrubbed.
install_redaction_map_filter()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    await create_all()
    yield


app = FastAPI(title="Guide Generator API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router.router)
app.include_router(files_router.router)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
