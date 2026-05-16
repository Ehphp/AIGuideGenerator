"""Phase A: API surface must scrub raw OCR/UI/redaction-map material from
`pipeline_artifacts` regardless of what the worker writes to the column."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.pipeline.common import PUBLIC_STAGE_KEYS, public_artifacts
from app.schemas.session import SessionRead


def _make_session_dict(artifacts: dict) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid.uuid4(),
        "title": "t",
        "status": "ready",
        "progress_message": None,
        "source_type": "uploaded",
        "media_key": None,
        "media_mime": None,
        "media_duration_sec": None,
        "media_size_bytes": None,
        "pipeline_artifacts": artifacts,
        "pipeline_events": [],
        "ai_usage": {},
        "guide_content": None,
        "guide_schema_version": None,
        "guide_edited_at": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def test_public_artifacts_drops_unknown_stage_keys():
    raw = {
        "ingest": {"ok": True},
        "rogue_stage": {"ok": True},
        "redaction_map": {"[EMAIL_1]": "user@example.com"},
        "redaction_map.local": {"[EMAIL_1]": "user@example.com"},
    }
    out = public_artifacts(raw)
    assert "ingest" in out
    assert "rogue_stage" not in out
    assert "redaction_map" not in out
    assert "redaction_map.local" not in out


def test_public_artifacts_scrubs_sensitive_field_names_recursively():
    raw = {
        "analyze_frames": {
            "summary_count": 2,
            "frames": [
                {
                    "ts": 1.0,
                    "ocr_text": "Email me at user@example.com — case INC123456",
                    "ui_summary": "User typed password Pa$$word into login form",
                },
                {"ts": 2.0, "ocr_text": "another secret", "ui_summary": "x"},
            ],
        }
    }
    out = public_artifacts(raw)
    serialized = repr(out)
    assert "user@example.com" not in serialized
    assert "INC123456" not in serialized
    assert "Pa$$word" not in serialized
    # Non-sensitive fields preserved.
    assert out["analyze_frames"]["summary_count"] == 2
    assert out["analyze_frames"]["frames"][0]["ts"] == 1.0
    assert "ocr_text" not in out["analyze_frames"]["frames"][0]
    assert "ui_summary" not in out["analyze_frames"]["frames"][0]


def test_public_artifacts_drops_nested_redaction_map_keys():
    raw = {
        "sanitize_timeline": {
            "placeholder_count": 4,
            "redaction_map_path": "/tmp/secret.json",  # nested key with hint
            "categories": ["EMAIL", "IBAN"],
        }
    }
    out = public_artifacts(raw)
    assert "redaction_map_path" not in out["sanitize_timeline"]
    assert out["sanitize_timeline"]["placeholder_count"] == 4
    assert out["sanitize_timeline"]["categories"] == ["EMAIL", "IBAN"]


def test_session_read_filters_through_public_artifacts():
    raw_artifacts = {
        "analyze_frames": {
            "frames": [
                {"ocr_text": "secret@example.com", "ui_summary": "leak"}
            ]
        },
        "redaction_map.local": {"[EMAIL_1]": "secret@example.com"},
        "ingest": {"ok": True},
    }
    obj = _make_session_dict(raw_artifacts)
    dumped = SessionRead.model_validate(obj).model_dump()
    artifacts = dumped["pipeline_artifacts"]
    rendered = repr(artifacts)
    assert "secret@example.com" not in rendered
    assert "redaction_map" not in artifacts
    assert "redaction_map.local" not in artifacts
    assert artifacts["ingest"] == {"ok": True}


def test_public_stage_keys_contains_known_phase_a_e_stages():
    # Sanity: confirm the allowlist accepts the stage names used by the
    # current pipeline AND the new Phase C–E stages.
    expected = {
        "ingest",
        "extract_audio",
        "transcribe",
        "extract_frames",
        "analyze_frames",
        "build_timeline",
        "generate_guide",
        "validate_guide",
        "transcribe_local",
        "ocr_frames_local",
        "build_raw_timeline",
        "sanitize_timeline",
        "rehydrate_guide",
    }
    assert expected.issubset(PUBLIC_STAGE_KEYS)


def test_public_artifacts_handles_none_and_empty():
    assert public_artifacts(None) == {}
    assert public_artifacts({}) == {}


def test_public_artifacts_does_not_mutate_input():
    raw = {"analyze_frames": {"frames": [{"ocr_text": "x"}]}}
    snapshot = repr(raw)
    public_artifacts(raw)
    assert repr(raw) == snapshot


def test_session_read_does_not_leak_raw_ocr_or_ui_summary():
    """Phase D regression: raw OCR text and ui_summary written by
    `ocr_frames_local` under the `analyze_frames` artifact key must NEVER
    reach the API surface, even if the worker stored them in the DB column.
    """
    raw_artifacts = {
        "analyze_frames": {
            "frames": [
                {
                    "ocr_text": "SECRET_CUSTOMER_DATA INC000123 Mario Rossi",
                    "ui_summary": "Sensitive UI summary",
                }
            ]
        }
    }
    obj = _make_session_dict(raw_artifacts)
    dumped = SessionRead.model_validate(obj).model_dump()
    rendered = repr(dumped["pipeline_artifacts"])

    # PII and raw payload must be absent from the serialized public surface.
    assert "SECRET_CUSTOMER_DATA" not in rendered
    assert "INC000123" not in rendered
    assert "Mario Rossi" not in rendered
    assert "ocr_text" not in rendered
    assert "Sensitive UI summary" not in rendered
    assert "ui_summary" not in rendered
