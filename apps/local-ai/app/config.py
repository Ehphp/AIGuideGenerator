"""Configuration for the local-ai service."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Read-only mount for resolving storage keys produced by the api / worker.
    storage_root: str = "/data/storage"

    # Server bind. Compose maps NO host port; service is internal-only.
    host: str = "0.0.0.0"
    port: int = 9000

    # Engine selection. Real engines arrive in Phase C (STT) / D (OCR).
    # 'stub'           — return empty results immediately; no model loaded.
    # 'faster_whisper' — use faster-whisper for STT (Phase C).
    # 'tesseract'      — use pytesseract for OCR (Phase D).
    # 'paddle'         — placeholder, not implemented yet.
    stt_engine: str = "stub"          # 'stub' | 'faster_whisper'
    ocr_engine: str = "stub"          # 'stub' | 'tesseract' | 'paddle'

    # faster-whisper knobs (Phase C). Defaults are lightweight / CPU-safe.
    whisper_model: str = "small"      # e.g. tiny / base / small / medium / large-v3
    whisper_device: str = "cpu"       # 'cpu' | 'cuda'
    whisper_compute_type: str = "int8" # int8 / float16 / float32
    whisper_language: str = ""        # blank = auto-detect

    # OCR knobs (Phase D). For Tesseract use codes like "eng", "ita+eng".
    # `ocr_lang` kept as backward-compat alias; new code reads `ocr_language`.
    ocr_language: str = "eng+ita"
    ocr_lang: str = "eng+ita"
    # Drop OCR blocks below this normalized (0..1) confidence. 0.0 keeps all.
    ocr_min_confidence: float = 0.0
    # Safety cap so a single /ocr request can't pin the worker.
    ocr_max_frames_per_request: int = 200


settings = Settings()
