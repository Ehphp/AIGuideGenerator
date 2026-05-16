# Guide Generator

Record a screen-based procedure (with mic audio) or upload a video, and automatically generate a structured, editable step-by-step guide.

## Status: MVP — Phase 0 (bootstrap)

This is a **local development MVP**. It is **not** intended for public deployment:

- No authentication.
- No multi-tenancy.
- File access is open within the running container.
- Database data is disposable until Alembic migrations are introduced (run `docker compose down -v` to reset).

## Requirements

- Docker Desktop (or Docker Engine) with Docker Compose v2.
- An `OPENAI_API_KEY` (only required from Phase 3 onward).

## Quick start

```bash
cp .env.example .env
# edit .env if needed
docker compose up --build
```

Services:

- Web (Next.js): http://localhost:3000
- API (FastAPI): http://localhost:8000 — health: http://localhost:8000/health
- Worker: runs in its own container, no exposed port.
- Postgres: localhost:5432 (inside the compose network: `postgres:5432`).

## Architecture

See `/memories/session/plan.md` (planning notes) for the full architecture, data model, AI pipeline, and implementation phases.

Top-level layout:

```
guide-generator/
├── docker-compose.yml
├── .env.example
├── data/                # gitignored: postgres volume + media storage
└── apps/
    ├── api/             # FastAPI + worker (one Python package)
    └── web/             # Next.js 14 (App Router)
```

## Resetting local state

```bash
docker compose down -v
rm -rf data/storage
```

## License

Proprietary / TBD.
