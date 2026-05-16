"""Phase E: detector catalog regression tests."""
from __future__ import annotations

from app.sanitize.categories import DETECTORS, detect_all


def _categories(text: str) -> list[str]:
    return [d.category for d, _ in detect_all(text)]


def _hits(text: str) -> dict[str, str]:
    """Return {category: matched_value_or_group} for debugging."""
    result = {}
    for det, m in detect_all(text):
        value = m.group(det.value_group) if det.value_group else m.group(0)
        result[det.category] = value
    return result


def test_email_detected():
    assert "EMAIL" in _categories("contact me at user@example.com please")


def test_email_not_detected_in_plain_text():
    assert "EMAIL" not in _categories("contact me later please")


def test_ipv4_detected():
    assert "IPV4" in _categories("server 10.0.0.1 down")


def test_url_detected():
    assert "URL" in _categories("see https://example.com/path?x=1")


def test_iban_detected():
    assert "IBAN" in _categories("IBAN IT60X0542811101000000123456")


def test_fiscal_code_detected():
    # Standard Italian CF format.
    assert "FISCAL_CODE" in _categories("CF: RSSMRA85M01H501Z grazie")


def test_api_key_detected():
    assert "API_KEY" in _categories("token sk-abcdefghijklmnopqrstuvwxyz1234567890")


def test_ticket_id_jira_style():
    assert "TICKET_ID" in _categories("ticket PROJ-1234 closed")


def test_ticket_id_servicenow_style():
    assert "TICKET_ID" in _categories("incident INC0012345 escalated")


def test_file_path_windows():
    assert "FILE_PATH" in _categories(r"open C:\Users\Mario\Documents\file.txt now")


def test_file_path_posix():
    assert "FILE_PATH" in _categories("see /etc/passwd config")


def test_priority_api_key_over_token():
    # API_KEY appears before generic patterns; ensure it wins.
    cats = _categories("sk-abcdefghijklmnopqrstuvwxyz1234567890")
    assert cats and cats[0] == "API_KEY"


def test_safe_text_yields_no_hits():
    assert _categories("Click the Settings button to continue.") == []


def test_detectors_have_unique_categories():
    cats = [d.category for d in DETECTORS]
    assert len(cats) == len(set(cats))


# ---------------------------------------------------------------------------
# PASSWORD detector tests
# ---------------------------------------------------------------------------


def test_password_plain_colon_detected():
    assert "PASSWORD" in _categories("password: Mario123!")


def test_password_uppercase_equals_detected():
    assert "PASSWORD" in _categories("Password = Test@123")


def test_password_pwd_equals_detected():
    assert "PASSWORD" in _categories("pwd=abc123")


def test_password_passwd_colon_detected():
    assert "PASSWORD" in _categories("passwd: MySecret123")


def test_password_passcode_colon_detected():
    assert "PASSWORD" in _categories("passcode: 123456")


def test_password_secret_colon_detected():
    assert "PASSWORD" in _categories("secret: valoreSegreto")


def test_password_json_double_quote_detected():
    assert "PASSWORD" in _categories('"password": "secret123"')


def test_password_json_single_quote_detected():
    assert "PASSWORD" in _categories("'password': 'secret123'")


def test_password_inline_double_quote_equals_detected():
    assert "PASSWORD" in _categories('password="secret123"')


def test_password_inline_single_quote_equals_detected():
    assert "PASSWORD" in _categories("password='secret123'")


def test_password_value_only_captured_not_label():
    """The captured value must be only the secret, not `password: secret`."""
    hits = _hits("password: Mario123!")
    assert hits.get("PASSWORD") == "Mario123!"


def test_password_json_value_only_captured():
    """For JSON form, value must not include surrounding quotes."""
    hits = _hits('"password": "secret123"')
    assert hits.get("PASSWORD") == "secret123"


def test_password_too_short_not_detected():
    # 2-char value < default min_length of 4.
    assert "PASSWORD" not in _categories("pwd=ab")


def test_password_keyword_alone_not_detected():
    # No separator → no match.
    assert "PASSWORD" not in _categories("click the password field")
    assert "PASSWORD" not in _categories("password field is empty")


def test_password_in_file_path_not_detected():
    # /etc/passwd is a FILE_PATH; the `passwd:` substring must not also
    # trigger PASSWORD because the lookbehind prevents it.
    cats = _categories("see /etc/passwd config")
    assert "PASSWORD" not in cats
    assert "FILE_PATH" in cats


def test_password_priority_after_api_key():
    """An API key used as a password value must be tagged as API_KEY, not PASSWORD."""
    # `secret: sk-<20+ chars>` — API_KEY occupies that value span first.
    cats = _categories("secret: sk-abcdefghijklmnopqrstuvwxyz1234567890")
    assert "API_KEY" in cats
    assert "PASSWORD" not in cats


def test_password_already_placeholder_not_rematched():
    # If the value is already a placeholder, don't re-redact it.
    assert "PASSWORD" not in _categories("password: [PASSWORD_1]")
