"""Phase E: Sanitizer behaviour."""
from __future__ import annotations

from app.sanitize import Sanitizer, rehydrate_text


def test_repeated_value_gets_same_placeholder():
    s = Sanitizer()
    out1 = s.sanitize_text("contact user@example.com")
    out2 = s.sanitize_text("write to user@example.com again")
    # Same email → same placeholder index.
    assert out1.endswith("[EMAIL_1]")
    assert out2.endswith("[EMAIL_1] again")


def test_distinct_values_get_distinct_placeholders():
    s = Sanitizer()
    out = s.sanitize_text("a@x.it then b@x.it then a@x.it")
    assert "[EMAIL_1]" in out
    assert "[EMAIL_2]" in out
    # First email must have stayed [EMAIL_1] on third occurrence.
    assert out.count("[EMAIL_1]") == 2
    assert out.count("[EMAIL_2]") == 1


def test_per_category_counters_independent():
    s = Sanitizer()
    out = s.sanitize_text("email a@x.it ip 10.0.0.1 email b@x.it")
    assert "[EMAIL_1]" in out
    assert "[EMAIL_2]" in out
    assert "[IPV4_1]" in out


def test_sanitize_timeline_scrubs_event_text_fields():
    s = Sanitizer()
    timeline = {
        "language": "it",
        "events": [
            {"kind": "transcript", "t": 0.0, "t_end": 1.0, "text": "mail a@x.it"},
            {
                "kind": "frame",
                "t": 1.5,
                "frame_key": "frames/000.jpg",
                "ocr_text": "IP 10.0.0.1",
                "ui_summary": "Login screen",
            },
        ],
    }
    result = s.sanitize_timeline(timeline)
    assert result.sanitized["events"][0]["text"] == "mail [EMAIL_1]"
    assert result.sanitized["events"][1]["ocr_text"] == "IP [IPV4_1]"
    # Frame key (not a sensitive field) preserved verbatim.
    assert result.sanitized["events"][1]["frame_key"] == "frames/000.jpg"
    assert result.report["categories"] == {"EMAIL": 1, "IPV4": 1}
    assert result.redaction_map["[EMAIL_1]"] == "a@x.it"
    assert result.redaction_map["[IPV4_1]"] == "10.0.0.1"


def test_round_trip_via_rehydrate_text():
    s = Sanitizer()
    text = "contact a@x.it then again a@x.it"
    sanitized = s.sanitize_text(text)
    rmap = dict(s._placeholder_to_value)
    rehydrated, stats = rehydrate_text(sanitized, rmap)
    assert rehydrated == text
    assert stats.unresolved == 0


def test_unknown_placeholder_left_intact():
    rehydrated, stats = rehydrate_text("hi [EMAIL_99]!", {})
    assert rehydrated == "hi [EMAIL_99]!"
    assert stats.unresolved == 1
    assert stats.resolved == 0


def test_safe_timeline_produces_no_placeholders():
    s = Sanitizer()
    timeline = {
        "language": "en",
        "events": [{"kind": "transcript", "t": 0.0, "t_end": 1.0, "text": "click Next"}],
    }
    result = s.sanitize_timeline(timeline)
    assert result.report["placeholders_total"] == 0
    assert result.redaction_map == {}
    assert result.sanitized["events"][0]["text"] == "click Next"


# ---------------------------------------------------------------------------
# value_group behaviour — PASSWORD category
# ---------------------------------------------------------------------------


def test_password_prefix_preserved_in_output():
    """Keyword label and separator must survive in the sanitized text."""
    s = Sanitizer()
    out = s.sanitize_text("password: Secret123!")
    assert out == "password: [PASSWORD_1]"


def test_password_json_quotes_preserved():
    """Surrounding quotes must be preserved for JSON-style inputs."""
    s = Sanitizer()
    out = s.sanitize_text('"password": "secret123"')
    assert out == '"password": "[PASSWORD_1]"'


def test_password_single_quotes_preserved():
    s = Sanitizer()
    out = s.sanitize_text("'password': 'secret123'")
    assert out == "'password': '[PASSWORD_1]'"


def test_password_equals_form():
    s = Sanitizer()
    out = s.sanitize_text("pwd=abc123")
    assert out == "pwd=[PASSWORD_1]"


def test_password_secret_keyword():
    s = Sanitizer()
    out = s.sanitize_text("secret: valoreSegreto")
    assert out == "secret: [PASSWORD_1]"


def test_password_redaction_map_stores_bare_value_not_full_match():
    """The redaction map must contain only the raw secret, not `password: secret`."""
    s = Sanitizer()
    s.sanitize_text("password: Secret123!")
    assert s._placeholder_to_value["[PASSWORD_1]"] == "Secret123!"


def test_password_round_trip_via_rehydrate():
    s = Sanitizer()
    original = "password: Secret123!"
    sanitized = s.sanitize_text(original)
    assert sanitized == "password: [PASSWORD_1]"

    rmap = dict(s._placeholder_to_value)
    rehydrated, stats = rehydrate_text(sanitized, rmap)
    assert rehydrated == original
    assert stats.unresolved == 0


def test_password_json_round_trip():
    s = Sanitizer()
    original = '"password": "secret123"'
    sanitized = s.sanitize_text(original)
    assert sanitized == '"password": "[PASSWORD_1]"'

    rmap = dict(s._placeholder_to_value)
    rehydrated, stats = rehydrate_text(sanitized, rmap)
    assert rehydrated == original
    assert stats.unresolved == 0


def test_password_and_email_both_redacted():
    """A text containing both an email and a password must mask both."""
    s = Sanitizer()
    out = s.sanitize_text("login user@example.com with password: Secret123!")
    assert "[EMAIL_1]" in out
    assert "[PASSWORD_1]" in out
    # Raw values must not survive.
    assert "user@example.com" not in out
    assert "Secret123!" not in out


def test_password_in_ocr_text_field():
    """Passwords inside OCR text must be redacted by sanitize_timeline."""
    s = Sanitizer()
    timeline = {
        "language": "it",
        "events": [
            {
                "kind": "frame",
                "t": 1.0,
                "frame_key": "sessions/x/frames/001.jpg",
                "ocr_text": "pwd=SuperSecret9",
                "ui_summary": "Login dialog",
            }
        ],
    }
    result = s.sanitize_timeline(timeline)
    assert result.sanitized["events"][0]["ocr_text"] == "pwd=[PASSWORD_1]"
    assert result.redaction_map["[PASSWORD_1]"] == "SuperSecret9"
    # Non-sensitive fields pass through unchanged.
    assert result.sanitized["events"][0]["frame_key"] == "sessions/x/frames/001.jpg"


def test_password_same_value_same_placeholder():
    """Two identical passwords in the same session get the same placeholder."""
    s = Sanitizer()
    out1 = s.sanitize_text("password: MyPass1")
    out2 = s.sanitize_text("secret: MyPass1")
    # Both reference the same raw value → same placeholder.
    assert "[PASSWORD_1]" in out1
    assert "[PASSWORD_1]" in out2
    assert len(s._placeholder_to_value) == 1


def test_password_distinct_values_distinct_placeholders():
    s = Sanitizer()
    out = s.sanitize_text("password: Alpha123 then password: Beta456")
    assert "[PASSWORD_1]" in out
    assert "[PASSWORD_2]" in out
    assert "Alpha123" not in out
    assert "Beta456" not in out
