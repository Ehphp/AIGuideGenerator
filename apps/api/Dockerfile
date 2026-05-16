FROM python:3.11-slim

# ffmpeg/ffprobe are required by the AI pipeline (used from Phase 3 onward, installed now).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e ".[dev]"

# Source is bind-mounted via docker-compose for hot reload, but copy as a fallback.
COPY . /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
