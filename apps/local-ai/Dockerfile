FROM python:3.11-slim

# Phase D: install Tesseract OCR engine + English/Italian language data.
# faster-whisper (Phase C) ships its own native deps via the wheel, so no
# extra apt packages are needed for STT on CPU.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-ita \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
# `[stt]` pulls in faster-whisper, `[ocr]` pulls in pytesseract+Pillow. In
# stub mode (STT_ENGINE=stub / OCR_ENGINE=stub) neither model is loaded and
# the image starts without any download.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e ".[stt,ocr,dev]"

# Source is bind-mounted via docker-compose for hot reload; copy as fallback.
COPY . /app

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
