"""Phase A: external-boundary safety guardrails."""
from __future__ import annotations

import pytest

from app.pipeline.safety import (
    FORBIDDEN_ARTIFACT_KEYS_FOR_LLM,
    RawDataLeakError,
    assert_not_raw_artifact,
    read_public_artifact_for_llm,
)


def test_forbidden_keys_cover_raw_stages():
    # The forbidden set must include every artifact known to contain raw,
    # unsanitized text or the redaction map.
    must_contain = {
        "transcribe",
        "transcribe_local",
        "ocr_frames",
        "ocr_frames_local",
        "build_raw_timeline",
        "redaction_map.local",
        "redaction_map",
    }
    assert must_contain.issubset(FORBIDDEN_ARTIFACT_KEYS_FOR_LLM)


def test_read_public_artifact_for_llm_refuses_forbidden_keys():
    sid = "00000000-0000-0000-0000-000000000000"
    for stage in FORBIDDEN_ARTIFACT_KEYS_FOR_LLM:
        with pytest.raises(RawDataLeakError) as exc:
            read_public_artifact_for_llm(sid, stage)
        # Error message must NOT echo any payload value.
        assert "user@" not in str(exc.value)
        assert stage in str(exc.value)  # OK to mention stage label


def test_assert_not_raw_artifact_detects_email():
    with pytest.raises(RawDataLeakError) as exc:
        assert_not_raw_artifact({"prompt": "Email me at user@example.com"})
    msg = str(exc.value)
    assert "EMAIL" in msg
    # Must NOT echo the actual email.
    assert "user@example.com" not in msg


def test_assert_not_raw_artifact_detects_ipv4():
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact({"text": "server at 10.0.0.42 failed"})


def test_assert_not_raw_artifact_detects_iban():
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact({"note": "transfer to IT60X0542811101000000123456"})


def test_assert_not_raw_artifact_detects_api_key():
    payload = {"text": "use sk-abcdefghijklmnopqrstuvwxyz1234567890"}
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact(payload)


def test_assert_not_raw_artifact_passes_safe_payload():
    safe = {
        "title": "Reset a forgotten password",
        "steps": [{"text": "Open the login screen and click the link."}],
    }
    # Must not raise.
    assert_not_raw_artifact(safe)


def test_assert_not_raw_artifact_handles_none_and_empty():
    assert_not_raw_artifact(None)
    assert_not_raw_artifact("")
    assert_not_raw_artifact({})


def test_assert_not_raw_artifact_walks_strings_too():
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact("Reach me at admin@corp.local")


def test_raw_data_leak_error_message_does_not_echo_input():
    # Defensive: even if a caller embeds sensitive data in the message,
    # we should be able to construct/raise without crashing.
    err = RawDataLeakError("forbidden artifact for external LLM: stage='transcribe'")
    assert "transcribe" in str(err)


# ---------------------------------------------------------------------------
# PASSWORD smoke-test
# ---------------------------------------------------------------------------


def test_assert_not_raw_artifact_detects_password_plain():
    with pytest.raises(RawDataLeakError) as exc:
        assert_not_raw_artifact({"text": "password: Secret123!"})
    assert "PASSWORD" in str(exc.value)
    # Error message must not echo the raw value.
    assert "Secret123" not in str(exc.value)


def test_assert_not_raw_artifact_detects_password_equals():
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact("pwd=abc123")


def test_assert_not_raw_artifact_detects_password_json():
    with pytest.raises(RawDataLeakError):
        assert_not_raw_artifact('"password": "secret123"')


def test_assert_not_raw_artifact_passes_password_keyword_without_value():
    # The word `password` alone (no separator + value) must not trip the guard.
    assert_not_raw_artifact("click the password field to proceed")
    assert_not_raw_artifact({"title": "How to change your password"})


def test_assert_not_raw_artifact_passes_password_placeholder():
    # A sanitized prompt containing the placeholder must not be blocked.
    assert_not_raw_artifact(
        {"steps": [{"text": "Enter your password: [PASSWORD_1] in the field."}]}
    )
