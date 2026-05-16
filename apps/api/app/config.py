"""Application configuration loaded from environment variables.

Phase 0 only loads the bare minimum needed for the API to start.
Additional fields will be added as later phases require them.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # API
    cors_allow_origins: str = "http://localhost:3000"

    # Storage (absolute path inside container)
    storage_dir: str = "/data/storage"

    # Limits
    max_recording_mb: int = 500
    max_frames: int = 40

    # Database
    database_url: str = "postgresql+asyncpg://guide:guide@postgres:5432/guide"

    # Worker
    worker_poll_interval_sec: float = 2.0
    # Phase 1 stub: how long the fake handler "processes" a recording.
    worker_stub_delay_sec: float = 2.0

    # Allowed media MIME types for upload
    allowed_media_mimes: str = "video/mp4,video/webm,video/quicktime,video/x-matroska"

    # AI (unused in Phase 0)
    openai_api_key: str = ""
    transcribe_language: str = ""
    openai_stt_model: str = "whisper-1"
    openai_vision_model: str = "gpt-4o"
    openai_llm_model: str = "gpt-4o"

    # Pipeline (Phase 3)
    ai_provider: str = "openai"  # 'openai' or 'fake' (tests)
    frames_uniform_interval_sec: float = 5.0
    frames_scene_threshold: float = 0.3
    frames_phash_distance: int = 6
    audio_sample_rate: int = 16000
    vision_max_concurrency: int = 1

    # Privacy / local-ai (Phases A–F). Defaults preserve current behavior.
    # Per-capability provider selection (decoupled from monolithic ai_provider).
    stt_provider: str = "openai"          # 'openai' | 'local' | 'fake'
    ocr_provider: str = "openai"          # 'openai' | 'local' | 'fake' | 'none'
    guide_llm_provider: str = "openai"    # 'openai' | 'fake'

    # local-ai service (Phase B onwards). Internal-only base URL.
    local_ai_base_url: str = "http://local-ai:9000"
    local_ai_timeout_seconds: float = 600.0
    local_ai_connect_timeout_sec: float = 10.0

    # local-ai engine config (Phase C / D).
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    ocr_engine: str = "paddle"            # 'paddle' | 'tesseract'
    ocr_lang: str = "eng+ita"            # Tesseract language codes; was "en+it" (invalid)
    ocr_max_concurrency: int = 2

    # Sanitizer (Phase E). Dormant in Phase A.
    sanitize_enabled: bool = False
    sanitize_strict_mode: bool = False
    # Minimum number of characters a password value must have to be redacted.
    # Reducing this below 4 increases false-positive risk significantly.
    sanitize_password_min_length: int = 4
    # Additional domain-specific PII patterns injected at startup.
    # Format: semicolon-separated "CATEGORY:regex" entries.
    # Example: CUSTOMER_ID:\bCUST-\d{6}\b;CONTRACT:\bCONT-[A-Z]{3}-\d{5}\b
    sanitize_custom_patterns: str = ""

    # OCR egress quality (Phase G).
    # Minimum Tesseract word-confidence (0.0–1.0) for a token to be included
    # in the timeline OCR text sent to the LLM.  0.0 disables filtering.
    ocr_confidence_min: float = 0.0

    # Evidence matching (Phase F).
    # Maximum distance (seconds) for the nearest-frame fallback when no frame
    # falls inside the step's [t_start, t_end] range.
    evidence_max_nearest_sec: float = 3.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def allowed_mimes_set(self) -> set[str]:
        return {m.strip() for m in self.allowed_media_mimes.split(",") if m.strip()}


settings = Settings()
