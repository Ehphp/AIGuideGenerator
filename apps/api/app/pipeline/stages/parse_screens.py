"""Stage: parse_screens — diagnostic per-frame screen view.

Pure derivation stage. Reads ``analyze_frames.json`` (raw OCR) and
``visual_facts.json`` (already classified UI elements) and writes
``parse_screens.json`` — a compact, human-inspectable artifact whose
sole purpose is to make it obvious *frame by frame* whether the OCR
is producing operationally useful information.

This stage:
  * does NOT load images
  * does NOT call any LLM
  * is NOT consumed by ``build_timeline``, ``generate_guide`` or any
    downstream stage. It is purely diagnostic / preparatory for a
    future ``infer_actions`` stage.
  * is idempotent and safely skippable if ``visual_facts`` is missing.

Per-frame schema (``parse_screens.json["frames"][i]``)::

    {
        "t": 12.34,
        "frame_key": "sessions/<id>/frames/frame_0007.jpg",
        "idx": 7,
        "screen_type": "form_page" | "terminal" | "error_screen" | ...,
        "app_hint": "github_web" | "vscode" | ... | null,
        "screen_title": "Create a new repository" | null,
        "ocr_text": "...",                     # cleaned (main content)
        "ui_hints": {
            "has_terminal": false,
            "has_code": false,
            "has_browser": true,
            "has_form": true,
            "has_buttons": true,
            "has_error_message": false,
            "has_success_message": false
        },
        "important_text": ["Repository name", "Private", "Create repository"],
        "uncertainties": ["low_ocr_yield", "no_screen_title"],
        "confidence": 0.42                     # informativeness_score
    }
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.pipeline import common

log = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.0"

# Max items kept in important_text per frame.
_MAX_IMPORTANT_TEXT = 8

# Cap raw ocr_text length stored in the diagnostic artifact (keep it small).
_MAX_OCR_TEXT_CHARS = 600

# Below this informativeness_score the frame gets the `low_ocr_yield` flag.
_LOW_YIELD_THRESHOLD = 0.15


# ---------------------------------------------------------------------------
# UI-hint regexes
# ---------------------------------------------------------------------------

# Strong terminal indicators: shell prompts, common CLI binaries, traceback frames.
_TERMINAL_RE = re.compile(
    r"(\$\s|>\s|PS\s[A-Z]:\\|"           # shell prompts
    r"\bbash\b|\bzsh\b|\bpwsh\b|"
    r"\bgit\s+(commit|push|pull|clone|status|add|checkout|branch)\b|"
    r"\bdocker\s+(run|ps|build|exec|compose)\b|"
    r"\bnpm\s+(install|run|start)\b|"
    r"\bpip\s+install\b|\bpython\s+\w|\bnode\s+\w|"
    r"\btraceback\b|\bsegmentation\sfault\b)",
    re.I,
)

# Code editor / source indicators.
_CODE_RE = re.compile(
    r"(\bdef\s+\w+\(|\bclass\s+\w+|\bfunction\s+\w+\(|"
    r"\bimport\s+\w+|\bfrom\s+\w+\s+import\b|"
    r"\bconst\s+\w+\s*=|\blet\s+\w+\s*=|\bvar\s+\w+\s*=|"
    r"</?[a-z][\w-]*\s|"                 # HTML/JSX tags
    r"\.tsx?\b|\.jsx?\b|\.py\b|\.go\b|\.rs\b)",
    re.I,
)

# Browser / web app indicators (URL bar fragments, common chrome).
_BROWSER_RE = re.compile(
    r"(https?://|"
    r"\blocalhost:\d+\b|"
    r"\bbookmarks?\b|\baddress\sbar\b|\bnew\stab\b)",
    re.I,
)

# Form indicators: labelled inputs / required-field markers.
_FORM_LABEL_WORDS: frozenset[str] = frozenset(
    {
        "name", "email", "password", "username", "address", "phone",
        "description", "title", "url", "repository", "branch",
        # Italian
        "nome", "cognome", "indirizzo", "telefono", "descrizione",
    }
)

_ERROR_RE = re.compile(
    r"\b(error|errore|exception|failed|failure|invalid|"
    r"unauthorized|forbidden|not\s+found|timeout|denied)\b",
    re.I,
)

_SUCCESS_RE = re.compile(
    r"\b(success|successful|completed|created|saved|uploaded|ok|done|"
    r"successo|completato|salvato)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# screen_type heuristic
# ---------------------------------------------------------------------------


def _infer_screen_type(
    ui_hints: dict[str, bool],
    visible_ui_elements: list[dict[str, Any]],
    app_context: str | None,
) -> str | None:
    """Coarse screen-type label from hints + element types.

    Order matters: error screens take precedence over form/terminal so
    that an error overlay isn't mislabelled as a form.
    """
    if ui_hints.get("has_error_message"):
        return "error_screen"
    if ui_hints.get("has_terminal"):
        return "terminal"
    if ui_hints.get("has_code") and (app_context == "vscode"):
        return "ide_editor"
    if ui_hints.get("has_form") and ui_hints.get("has_buttons"):
        return "form_page"
    if ui_hints.get("has_success_message"):
        return "success_screen"

    # Count list_items / nav_items as a "list/dashboard" signal.
    list_like = sum(
        1 for e in visible_ui_elements
        if e.get("type") in ("list_item", "navigation_item")
    )
    if list_like >= 3:
        return "list_view"

    if ui_hints.get("has_browser"):
        return "web_page"

    return None


# ---------------------------------------------------------------------------
# Pure helpers (exported for testing)
# ---------------------------------------------------------------------------


def compute_ui_hints(ocr_text: str, visible_ui_elements: list[dict[str, Any]]) -> dict[str, bool]:
    """Return boolean hints describing what the frame seems to contain.

    Pure function: takes the cleaned OCR text and the typed UI elements
    (as produced by extract_visual_facts) and returns a flat dict of bools.
    """
    text = ocr_text or ""
    elements = visible_ui_elements or []

    types = {e.get("type") for e in elements}

    has_buttons = "button" in types
    has_error_message = ("error_message" in types) or bool(_ERROR_RE.search(text))
    has_success_message = bool(_SUCCESS_RE.search(text))

    has_terminal = bool(_TERMINAL_RE.search(text))
    has_code = bool(_CODE_RE.search(text))
    has_browser = bool(_BROWSER_RE.search(text))

    # has_form: at least one button + at least one form-label-ish word in the text
    text_lower_words = {w.strip(":.,").lower() for w in text.split()}
    has_form_labels = bool(text_lower_words & _FORM_LABEL_WORDS)
    has_form = has_buttons and has_form_labels

    return {
        "has_terminal": has_terminal,
        "has_code": has_code,
        "has_browser": has_browser,
        "has_form": has_form,
        "has_buttons": has_buttons,
        "has_error_message": has_error_message,
        "has_success_message": has_success_message,
    }


def select_important_text(
    visible_ui_elements: list[dict[str, Any]],
    max_items: int = _MAX_IMPORTANT_TEXT,
) -> list[str]:
    """Top-N labels from typed UI elements, ranked by role/confidence.

    Prefers titles, buttons, status badges, error messages, then list items
    and nav items. Ties broken by confidence desc. Deduplicated case-insensitive.
    """
    type_priority = {
        "title": 0,
        "error_message": 1,
        "status_badge": 2,
        "button": 3,
        "list_item": 4,
        "navigation_item": 5,
    }

    def _rank(el: dict[str, Any]) -> tuple[int, float]:
        return (
            type_priority.get(el.get("type") or "", 99),
            -float(el.get("confidence", 0.0)),
        )

    candidates = [
        e for e in (visible_ui_elements or [])
        if e.get("type") in type_priority and (e.get("label") or "").strip()
    ]
    candidates.sort(key=_rank)

    seen: set[str] = set()
    out: list[str] = []
    for el in candidates:
        label = (el.get("label") or "").strip()
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
        if len(out) >= max_items:
            break
    return out


def collect_uncertainties(
    visual_fact: dict[str, Any],
    ui_hints: dict[str, bool],
    important_text: list[str],
) -> list[str]:
    """Return a list of short uncertainty tags for human inspection."""
    flags: list[str] = []
    diag = visual_fact.get("diagnostics") or {}

    if diag.get("uncertain"):
        flags.append("region_filter_too_aggressive")

    info = float(visual_fact.get("informativeness_score") or 0.0)
    if info < _LOW_YIELD_THRESHOLD:
        flags.append("low_ocr_yield")

    if not visual_fact.get("screen_title"):
        flags.append("no_screen_title")

    if not important_text:
        flags.append("no_important_text")

    if not any(ui_hints.values()):
        flags.append("no_ui_signal")

    n_kept = int(diag.get("n_blocks_kept") or 0)
    if n_kept == 0:
        flags.append("no_blocks_kept")

    return flags


def build_summary(
    screen_type: str | None,
    screen_title: str | None,
    app_hint: str | None,
    important_text: list[str],
) -> str:
    """One-line human summary for quick eyeballing."""
    parts: list[str] = []
    if screen_type:
        parts.append(screen_type)
    if app_hint:
        parts.append(f"app={app_hint}")
    if screen_title:
        parts.append(f"title='{screen_title}'")
    if important_text:
        head = ", ".join(important_text[:4])
        parts.append(f"signals=[{head}]")
    return " | ".join(parts) if parts else "no signal"


# ---------------------------------------------------------------------------
# Per-frame derivation
# ---------------------------------------------------------------------------


def derive_frame(
    analyze_entry: dict[str, Any],
    visual_fact: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the parse_screens entry for a single frame.

    ``analyze_entry`` is one item from ``analyze_frames.json``.
    ``visual_fact`` is the matching item from ``visual_facts.json["frames"]``
    (may be ``None`` when extract_visual_facts was skipped).
    """
    frame_key = analyze_entry.get("key") or analyze_entry.get("frame_key", "")
    idx = int(analyze_entry.get("idx", 0))
    t = float(analyze_entry.get("t", 0.0))

    visual_fact = visual_fact or {}
    visible_ui_elements = visual_fact.get("visible_ui_elements") or []

    # Prefer the cleaned main_content_text from visual_facts; fall back to raw OCR.
    cleaned_text = (
        visual_fact.get("main_content_text")
        or analyze_entry.get("ocr_text")
        or ""
    )
    if len(cleaned_text) > _MAX_OCR_TEXT_CHARS:
        cleaned_text = cleaned_text[: _MAX_OCR_TEXT_CHARS - 1].rstrip() + "…"

    ui_hints = compute_ui_hints(cleaned_text, visible_ui_elements)
    important_text = select_important_text(visible_ui_elements)
    app_hint = visual_fact.get("app_context")
    screen_type = _infer_screen_type(ui_hints, visible_ui_elements, app_hint)
    screen_title = visual_fact.get("screen_title")
    confidence = float(visual_fact.get("informativeness_score") or 0.0)
    uncertainties = collect_uncertainties(visual_fact, ui_hints, important_text)
    summary = build_summary(screen_type, screen_title, app_hint, important_text)

    return {
        "t": t,
        "idx": idx,
        "frame_key": frame_key,
        "screen_type": screen_type,
        "app_hint": app_hint,
        "screen_title": screen_title,
        "ocr_text": cleaned_text,
        "ui_hints": ui_hints,
        "important_text": important_text,
        "uncertainties": uncertainties,
        "confidence": round(confidence, 3),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


async def run(db: AsyncSession, session: Session) -> None:
    """Derive ``parse_screens.json`` from analyze_frames + visual_facts.

    Idempotent. No-op (with a recorded summary) if ``analyze_frames`` is
    missing. Tolerates a missing ``visual_facts`` artifact by degrading
    gracefully (only raw OCR text + minimal hints will be available).
    """
    if common.stage_done(session, "parse_screens"):
        log.info("parse_screens: already done, skipping")
        return

    analyze_data = common.read_artifact(session.id, "analyze_frames")
    if not isinstance(analyze_data, list) or not analyze_data:
        log.warning("parse_screens: analyze_frames missing or empty — skipping")
        await common.record_stage(
            db,
            session,
            stage="parse_screens",
            summary={"frame_count": 0, "skipped_reason": "no_analyze_frames"},
        )
        return

    vf_payload = common.read_artifact(session.id, "visual_facts")
    vf_by_key: dict[str, dict[str, Any]] = {}
    if isinstance(vf_payload, dict):
        for vf_frame in vf_payload.get("frames") or []:
            fk = vf_frame.get("frame_key")
            if fk:
                vf_by_key[fk] = vf_frame

    parsed: list[dict[str, Any]] = []
    for entry in analyze_data:
        try:
            fk = entry.get("key") or entry.get("frame_key")
            parsed.append(derive_frame(entry, vf_by_key.get(fk) if fk else None))
        except Exception:
            log.exception(
                "parse_screens: failed to derive frame idx=%s", entry.get("idx")
            )

    # Aggregate diagnostics — these are what makes "is OCR useful?" visible.
    n = len(parsed)

    def _hint_count(name: str) -> int:
        return sum(1 for f in parsed if f["ui_hints"].get(name))

    summary = {
        "schema_version": _SCHEMA_VERSION,
        "frame_count": n,
        "frames_with_screen_type": sum(1 for f in parsed if f["screen_type"]),
        "frames_with_screen_title": sum(1 for f in parsed if f["screen_title"]),
        "frames_with_app_hint": sum(1 for f in parsed if f["app_hint"]),
        "frames_with_important_text": sum(1 for f in parsed if f["important_text"]),
        "low_ocr_yield_frames": sum(
            1 for f in parsed if "low_ocr_yield" in f["uncertainties"]
        ),
        "no_ui_signal_frames": sum(
            1 for f in parsed if "no_ui_signal" in f["uncertainties"]
        ),
        "hints": {
            "has_terminal": _hint_count("has_terminal"),
            "has_code": _hint_count("has_code"),
            "has_browser": _hint_count("has_browser"),
            "has_form": _hint_count("has_form"),
            "has_buttons": _hint_count("has_buttons"),
            "has_error_message": _hint_count("has_error_message"),
            "has_success_message": _hint_count("has_success_message"),
        },
        "avg_confidence": (
            round(sum(f["confidence"] for f in parsed) / n, 3) if n else 0.0
        ),
    }

    payload = {
        "schema_version": _SCHEMA_VERSION,
        "frames": parsed,
        "summary": summary,
    }
    artifact_key = common.write_artifact(session.id, "parse_screens", payload)
    log.info(
        "parse_screens: wrote %s [frames=%d, with_type=%d, low_yield=%d]",
        artifact_key,
        n,
        summary["frames_with_screen_type"],
        summary["low_ocr_yield_frames"],
    )

    await common.record_stage(
        db,
        session,
        stage="parse_screens",
        summary=summary,
        message=(
            f"parsed {n} screens "
            f"(typed={summary['frames_with_screen_type']}, "
            f"low_yield={summary['low_ocr_yield_frames']})"
        ),
    )
