"""Detector catalog for the Phase E sanitizer.

Each detector is a `(category, regex)` pair. Detectors run in priority
order: more specific patterns first to avoid double-tokenization (e.g.
`API_KEY` before `TOKEN`, `IBAN` / `FISCAL_CODE` / `VAT` before generic
alphanumeric runs, `EMAIL` before `URL`/`HOSTNAME`).

The MVP detector set is intentionally conservative — high precision over
recall — to avoid over-redacting useful technical context. Person and
company name detection is deliberately omitted (deferred past MVP per
the plan).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Detector:
    category: str
    pattern: re.Pattern[str]
    # Normalize the captured value before keying it in the consistency map.
    # `lower` is safe for emails / domains / hex tokens; `as_is` for
    # everything that may be case-significant (e.g. ticket IDs, base64).
    normalize: str = "lower"  # "lower" | "as_is"
    # When set, only this named regex group is replaced by a placeholder;
    # the rest of the match (prefix keyword, quotes, etc.) is preserved in
    # the output.  When None (the default), the entire match is replaced —
    # this is the original behaviour and all existing detectors use it.
    value_group: str | None = None


# NOTE: Order matters. The first matching detector wins for a given span.

# ---------------------------------------------------------------------------
# PASSWORD pattern factory
#
# Built at module load time so the minimum-length threshold is read once from
# settings and baked into the compiled regex.  Changing
# SANITIZE_PASSWORD_MIN_LENGTH requires a process restart (standard behaviour
# for settings that affect compiled artefacts).
#
# Design notes:
#   • Keywords: password | passwd | passcode | pwd | secret.
#     `token` is deliberately excluded — partially covered by API_KEY.
#     Standalone `pass` is excluded — too ambiguous (Python keyword, English
#     word, path segments).
#   • Negative lookbehind (?<![/\\]) prevents matching `passwd` embedded
#     inside file-system paths such as `/etc/passwd:` or `C:\...\passwd:`.
#   • `value_group="value"` tells the Sanitizer to replace only that span,
#     preserving the keyword label and surrounding quotes in the output.
#     Input:   password: Secret123!
#     Output:  password: [PASSWORD_1]
#     Input:   "password": "Secret123!"
#     Output:  "password": "[PASSWORD_1]"
# ---------------------------------------------------------------------------

def _build_password_pattern(min_len: int) -> re.Pattern[str]:
    """Return a compiled PASSWORD regex with the given minimum value length."""
    value_quantifier = "{%d,}" % min_len
    return re.compile(
        # Optional opening quote + keyword (word-boundary protected) +
        # optional closing quote + separator (= or :) + optional opening
        # quote around the value.  The entire prefix is a non-capturing group
        # so it is preserved verbatim in the output when value_group is used.
        r'(?:(?<![/\\])["\']?\b'
        r'(?:password|passwd|passcode|pwd|secret)'
        r'\b["\']?\s*[=:]\s*["\']?)'
        # The value itself: must not start with [ (already a placeholder),
        # and must not contain whitespace, quotes, or common list separators.
        r'(?P<value>(?!\[)[^\s"\'\r\n,;]' + value_quantifier + r')'
        # Optional closing quote (mirrors the opening one consumed above).
        r'["\']?',
        re.IGNORECASE,
    )


# Lazy import to avoid a top-level dependency on config at import time in
# environments that do not set up the full settings object (e.g. bare unit
# tests that mock the module).  The function is called once at module load.
def _password_min_len() -> int:
    try:
        from app.config import settings  # noqa: PLC0415
        return settings.sanitize_password_min_length
    except Exception:  # pragma: no cover — defensive; settings always loads in prod
        return 4


DETECTORS: tuple[Detector, ...] = (
    # --- High-entropy / vendor-prefixed secrets first -----------------
    Detector(
        "API_KEY",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9]{20,}"
            r"|ghp_[A-Za-z0-9]{20,}"
            r"|gho_[A-Za-z0-9]{20,}"
            r"|xox[abprs]-[A-Za-z0-9-]{10,}"
            r"|AKIA[0-9A-Z]{16})\b"
        ),
        normalize="as_is",
    ),
    # --- Cleartext credentials (keyword + separator + value) ----------
    # Positioned after API_KEY so high-entropy secrets win for overlapping
    # spans (e.g. `secret: sk-...` is tagged as API_KEY, not PASSWORD).
    Detector(
        "PASSWORD",
        _build_password_pattern(_password_min_len()),
        normalize="as_is",
        value_group="value",
    ),
    # --- Italian financial identifiers --------------------------------
    Detector(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
        normalize="as_is",
    ),
    Detector(
        "FISCAL_CODE",
        # Italian Codice Fiscale: 6 letters + 2 digits + 1 letter + 2 digits +
        # 1 letter + 3 alnum + 1 letter (16 chars).
        re.compile(
            r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z][A-Z0-9]{3}[A-Z]\b",
            re.IGNORECASE,
        ),
        normalize="as_is",
    ),
    Detector(
        "VAT_NUMBER",
        # IT VAT: optional country prefix + 11 digits.
        re.compile(r"\b(?:IT)?\d{11}\b"),
        normalize="as_is",
    ),
    # --- Network identifiers ------------------------------------------
    Detector(
        "EMAIL",
        re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    ),
    Detector(
        "URL",
        re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE),
        normalize="as_is",
    ),
    Detector(
        "IPV4",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        normalize="as_is",
    ),
    Detector(
        "IPV6",
        # Conservative IPv6: 2+ hex groups separated by `:`. Must contain
        # at least one `::` or 4 groups to avoid matching MAC-like text.
        re.compile(
            r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b"
        ),
        normalize="lower",
    ),
    # --- Filesystem & user identifiers --------------------------------
    Detector(
        "FILE_PATH",
        # Windows absolute paths and POSIX absolute paths with at least
        # two segments. Avoids matching tokens like `/health`.
        re.compile(
            r"(?:[A-Za-z]:\\[^\s<>\"|?*]+"
            r"|/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)"
        ),
        normalize="as_is",
    ),
    Detector(
        "TICKET_ID",
        # Common ITSM patterns: INC0012345, REQ0012345, CHG0012345,
        # JIRA-style PROJ-1234.
        re.compile(
            r"\b(?:INC|REQ|CHG|TASK|PRB)\d{4,}\b|\b[A-Z]{2,10}-\d{1,7}\b"
        ),
        normalize="as_is",
    ),
    # --- Phone numbers (Italian + E.164) ------------------------------
    Detector(
        "PHONE",
        re.compile(
            r"\b(?:\+?\d{1,3}[ .\-]?)?(?:\(?\d{2,4}\)?[ .\-]?)?\d{6,10}\b"
        ),
        normalize="as_is",
    ),
)


def detect_all(text: str) -> list[tuple[Detector, re.Match[str]]]:
    """Return all non-overlapping detector hits in priority order.

    Earlier detectors win for overlapping spans (priority preserved by
    the `DETECTORS` tuple order).
    """
    if not text:
        return []
    occupied: list[tuple[int, int]] = []
    hits: list[tuple[Detector, re.Match[str]]] = []
    for det in DETECTORS:
        for m in det.pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(s < end and start < e for s, e in occupied):
                continue
            occupied.append((start, end))
            hits.append((det, m))
    hits.sort(key=lambda h: h[1].start())
    return hits


def _load_custom_detectors() -> tuple[Detector, ...]:
    """Build extra detectors from ``settings.sanitize_custom_patterns``.

    Format: semicolon-separated ``CATEGORY:regex`` entries.  Invalid entries
    (bad regex, missing colon, empty category) are silently skipped — they
    must not crash the sanitizer at startup.

    Example env value::

        SANITIZE_CUSTOM_PATTERNS=CUSTOMER_ID:\\bCUST-\\d{6}\\b;CONTRACT:\\bCONT-[A-Z]{3}-\\d{5}\\b
    """
    try:
        from app.config import settings  # noqa: PLC0415
        raw = (getattr(settings, "sanitize_custom_patterns", "") or "").strip()
    except Exception:
        return ()
    if not raw:
        return ()
    extras: list[Detector] = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        category, _, pattern_str = entry.partition(":")
        category = category.strip().upper()
        pattern_str = pattern_str.strip()
        if not category or not pattern_str:
            continue
        try:
            compiled = re.compile(pattern_str)
            extras.append(Detector(category, compiled, normalize="as_is"))
        except re.error:
            pass  # invalid regex — skip silently
    return tuple(extras)


# Extend the built-in catalog with any operator-supplied patterns.
# Appended last so built-in high-priority patterns always win for overlapping spans.
DETECTORS = DETECTORS + _load_custom_detectors()
