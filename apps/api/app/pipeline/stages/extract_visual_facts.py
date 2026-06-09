"""Stage: extract_visual_facts.

Deterministic post-OCR stage that transforms raw OCR blocks from
``analyze_frames.json`` into a structured ``visual_facts.json`` artifact.

Zero LLM calls.  Zero image loading.  Read-only of existing artifacts.

Produces
--------
``visual_facts.json``
    Per-frame structured visual representation: viewport, region exclusions,
    classified UI elements, inferred possible actions, informativeness score.

``pipeline_artifacts["extract_visual_facts"]``
    Aggregate summary stored in DB: frame counts, average informativeness,
    element density.

Goals (Phase 1 — audit only)
-----------------------------
- Filter OCR noise (browser chrome, taskbar, bookmarks, URLs, timestamps).
- Classify remaining blocks: title, button, list_item, status_badge, etc.
- Infer possible actions from classified elements.
- Produce an ``informativeness_score`` (0–1) per frame.

This stage intentionally does NOT modify ``build_timeline.py``,
``generate_guide.py``, the Guide schema, or any prompt.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.pipeline import common

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Geometric region thresholds (pixels)
# ---------------------------------------------------------------------------

# Blocks whose *top edge* falls in these pixel bands are likely browser chrome
# or OS chrome — not main application content.
_CHROME_TOP_PX: int = 130       # URL bar + tab strip + bookmark bar (typically y < 130)
_TASKBAR_BOTTOM_PX: int = 60    # Windows taskbar / macOS dock
_NAV_LEFT_PX: int = 200         # Left-side navigation / sidebar

# When region filtering removes more than this fraction of total blocks the
# frame is marked uncertain and filtering is applied more permissively.
_UNCERTAIN_THRESHOLD: float = 0.85

# Minimum confidence to retain a block at all.
_MIN_CONFIDENCE: float = 0.35

# ---------------------------------------------------------------------------
# Noise token lists
# ---------------------------------------------------------------------------

# Single-word lowercase tokens that are almost always noise in screen recordings.
_NOISE_EXACT: frozenset[str] = frozenset(
    {
        # English filler
        "the", "and", "for", "with", "this", "that", "from",
        "not", "new", "only", "show", "all", "more", "its",
        # Italian filler
        "il", "la", "le", "di", "da", "in", "su", "un", "una", "del",
        "dei", "che", "con", "non", "per", "una", "gli",
        # Browser / OS noise
        "meteo", "loginpage", "deepl", "linkedin", "google", "maps",
        "chatgpt", "microsoft", "chrome", "firefox", "safari", "edge",
        "posta", "arrivo", "cerca", "cercare",
        # HTTP / log tokens
        "get", "http", "https", "local", "host",
        # Date / time fragments
        "am", "pm",
        # Very common OCR garbage
        "rr", "ic", "ca", "ww", "ii", "oo", "vv",
    }
)

# Regex patterns: any block whose text matches is considered noise.
_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"https?://", re.I),             # full URLs
    re.compile(r"localhost:\d+", re.I),          # localhost:port
    re.compile(r"\d{1,2}:\d{2}", re.I),          # time HH:MM
    re.compile(r"\d{4}-\d{2}-\d{2}"),            # date YYYY-MM-DD
    re.compile(r"\d{2}/\d{2}/\d{4}"),            # date DD/MM/YYYY
    re.compile(r"[0-9a-f]{8,}", re.I),           # hex hashes / IDs
    re.compile(r"^\W+$"),                         # only punctuation / symbols
    re.compile(r'"GET\s+/', re.I),               # HTTP request log lines
    re.compile(r"^(record screen|upload file)$", re.I),  # tool chrome
    re.compile(r"^itguide", re.I),               # ITGuideGenerator chrome
    re.compile(
        r"^(deepl|linkedin|github|wikipedia|translate|youtube|amazon)",
        re.I,
    ),                                            # browser tab titles (external sites)
]

# Substring (lowercase) checks — if any of these appear in the block text,
# it is noise.
_NOISE_SUBSTRINGS: list[str] = [
    "loginpage",
    "deepl translate",
    "feed | linkedin",
    "feed|linkedin",
    "google news",
    "google maps",
    "lmarena",
    "power apps",
    "apps|home",
    "posta in arrivo",
    "record screen",
    "upload file",
    "itguidegenerator",
    "ilearn lms",
    "ilearnlms",
    "ilearn",
    "deepstatemap",
    "certificato micro",
    "localhost:3000",
    "localhost:8000",
    "localhost:8080",
    "localhost:5000",
    "localhost:5432",
]

# ---------------------------------------------------------------------------
# UI element classification vocabulary
# ---------------------------------------------------------------------------

_STATUS_BADGE_WORDS: frozenset[str] = frozenset(
    {
        "running", "exited", "created", "stopped", "paused", "restarting",
        "dead", "healthy", "unhealthy", "starting", "degraded",
        # Italian
        "avviato", "fermo", "attivo",
    }
)

# Status patterns like "running (5/5)", "exited (1)"
_STATUS_BADGE_RE = re.compile(
    r"^(running|exited|created|stopped|paused)\s*(\(\d+(?:/\d+)?\))?$",
    re.I,
)

_ERROR_WORDS: frozenset[str] = frozenset(
    {
        "error", "exception", "failed", "failure", "invalid", "unauthorized",
        "forbidden", "not found", "timeout", "crash", "panic",
        # Italian
        "errore", "eccezione", "fallito", "non trovato",
    }
)

_SUCCESS_WORDS: frozenset[str] = frozenset(
    {"success", "ok", "done", "complete", "completed", "successo"}
)

_BUTTON_WORDS: frozenset[str] = frozenset(
    {
        "save", "cancel", "submit", "next", "back", "login", "logout",
        "sign in", "sign out", "search", "find", "apply", "confirm",
        "delete", "remove", "add", "create", "edit", "update", "close",
        "continue", "finish", "done", "yes", "no", "accept", "decline",
        "retry", "refresh", "reload", "reset", "open", "view",
        # Italian
        "cerca", "salva", "annulla", "conferma", "elimina", "aggiungi",
        "modifica", "accetta", "rifiuta", "riprova", "aggiorna", "chiudi",
        "avanti", "indietro", "accedi",
    }
)

# Generic target words: labels that are too vague to appear in possible_actions.
_GENERIC_TARGET_WORDS: frozenset[str] = frozenset(
    {
        "button", "search button", "search field", "container", "menu",
        "field", "item", "option", "link", "result", "page", "tab", "icon",
        "input", "form", "list", "checkbox", "dropdown", "select", "text",
        "label", "element", "panel", "section", "area", "box", "dialog",
        "modal", "window", "header", "footer", "bar", "row", "column",
        "cell", "card", "widget", "column", "detail", "info", "help",
        "back", "next", "ok", "yes", "no",  # also too generic for targets
    }
)


# ---------------------------------------------------------------------------
# Noise category labels (reported in noise_text_removed)
# ---------------------------------------------------------------------------

_CAT_CHROME_TOP = "browser_chrome_top"
_CAT_TASKBAR = "taskbar_bottom"
_CAT_URL = "url_or_path"
_CAT_TIMESTAMP = "timestamp"
_CAT_TAB_TITLE = "tab_titles"
_CAT_LOW_CONFIDENCE = "low_confidence"
_CAT_OCR_GARBAGE = "ocr_garbage"
_CAT_SHORT_TOKEN = "short_token"


# ---------------------------------------------------------------------------
# Block normalisation
# ---------------------------------------------------------------------------


def _normalize_block(block: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise a raw OCR block dict.  Returns *None* if the block is unusable."""
    text: str = (block.get("text") or "").strip()
    if not text:
        return None
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 2:
        return None

    confidence: float = float(block.get("confidence", 0.0))

    raw_bbox = block.get("bbox", {})
    if isinstance(raw_bbox, dict):
        x = int(raw_bbox.get("x", 0))
        y = int(raw_bbox.get("y", 0))
        w = int(raw_bbox.get("w", 0))
        h = int(raw_bbox.get("h", 0))
    elif isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        x, y, w, h = (int(v) for v in raw_bbox[:4])
    else:
        x = y = w = h = 0

    return {
        "text": text,
        "confidence": confidence,
        "bbox": [x, y, w, h],
    }


# ---------------------------------------------------------------------------
# Noise detection
# ---------------------------------------------------------------------------


def _noise_category(text: str) -> str | None:
    """Return the noise category for *text*, or *None* if not noise."""
    t = text.strip()
    tl = t.lower()

    if len(t) < 2:
        return _CAT_SHORT_TOKEN

    # Only symbols / punctuation
    if re.fullmatch(r"[\W_]+", t):
        return _CAT_OCR_GARBAGE

    # URL / path
    for pat in _NOISE_PATTERNS[:2]:   # https://, localhost:
        if pat.search(tl):
            return _CAT_URL

    # Timestamp
    for pat in _NOISE_PATTERNS[2:4]:  # HH:MM, YYYY-MM-DD
        if pat.fullmatch(tl) or pat.search(tl):
            return _CAT_TIMESTAMP

    # Hex / request log
    for pat in _NOISE_PATTERNS[4:8]:
        if pat.search(tl):
            return _CAT_OCR_GARBAGE

    # Known browser / tool chrome
    for pat in _NOISE_PATTERNS[8:]:
        if pat.search(tl):
            return _CAT_TAB_TITLE

    # Substring check
    for ns in _NOISE_SUBSTRINGS:
        if ns.lower() in tl:
            return _CAT_TAB_TITLE

    # Exact single-word noise token
    if tl in _NOISE_EXACT:
        return _CAT_OCR_GARBAGE

    # Too many special characters (OCR garbage heuristic)
    alphanum = sum(1 for c in t if c.isalnum())
    if alphanum < len(t) * 0.45:
        return _CAT_OCR_GARBAGE

    return None


# ---------------------------------------------------------------------------
# Viewport estimation
# ---------------------------------------------------------------------------


def _estimate_viewport(blocks: list[dict[str, Any]]) -> dict[str, int]:
    """Estimate screen dimensions from block bounding boxes."""
    if not blocks:
        return {"w": 1920, "h": 1080}

    max_x = max((b["bbox"][0] + b["bbox"][2]) for b in blocks)
    max_y = max((b["bbox"][1] + b["bbox"][3]) for b in blocks)

    return {
        "w": max(max_x, 800),
        "h": max(max_y, 600),
    }


# ---------------------------------------------------------------------------
# Region filtering
# ---------------------------------------------------------------------------


def _filter_regions(
    blocks: list[dict[str, Any]],
    viewport: dict[str, int],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Remove blocks in browser-chrome / taskbar regions.

    Returns
    -------
    (kept, regions_excluded, uncertain)
        *uncertain* is True when region filtering would remove too many blocks;
        in that case the original block list is returned unchanged.
    """
    vh = viewport["h"]
    regions_excluded: list[str] = []
    kept: list[dict[str, Any]] = []
    dropped = 0

    for b in blocks:
        y = b["bbox"][1]
        if y < _CHROME_TOP_PX:
            dropped += 1
            if _CAT_CHROME_TOP not in regions_excluded:
                regions_excluded.append(_CAT_CHROME_TOP)
        elif y > vh - _TASKBAR_BOTTOM_PX:
            dropped += 1
            if _CAT_TASKBAR not in regions_excluded:
                regions_excluded.append(_CAT_TASKBAR)
        else:
            kept.append(b)

    total = len(blocks)
    if total > 0 and (dropped / total) > _UNCERTAIN_THRESHOLD:
        # Region filtering is too aggressive — likely wrong viewport estimate.
        return blocks, [], True

    return kept, regions_excluded, False


# ---------------------------------------------------------------------------
# UI element classification
# ---------------------------------------------------------------------------


def _element_type(
    text: str,
    bbox: list[int],
    viewport: dict[str, int],
) -> str:
    """Classify a block into a UI element type."""
    tl = text.lower().strip()
    x, y, w, h = bbox
    vw = viewport["w"]
    vh = viewport["h"]

    # Status badge — exact word or pattern
    if tl in _STATUS_BADGE_WORDS or _STATUS_BADGE_RE.fullmatch(tl):
        return "status_badge"

    # Success indicator
    if tl in _SUCCESS_WORDS:
        return "status_badge"

    # Error message — any error keyword anywhere in the text
    if any(ew in tl for ew in _ERROR_WORDS):
        return "error_message"

    # Button — exact match against known action words
    if tl in _BUTTON_WORDS:
        return "button"

    # Title — near top of the main content area, usually tall or wide
    content_top = _CHROME_TOP_PX + 20
    if y < content_top + 100 and (h >= 16 or w > vw * 0.3):
        return "title"

    # Navigation item — left side of screen, not too wide
    if x < _NAV_LEFT_PX and w < vw * 0.35:
        return "navigation_item"

    # List item — specific text in the main content area
    if (
        x >= _NAV_LEFT_PX - 20           # centre or right of nav
        and w < vw * 0.65               # not a full-width text blob
        and len(text) >= 3
        and not re.fullmatch(r"[\d\s\-:.,]+", text)  # not a number-only string
    ):
        # Compound identifiers (hyphenated names like "guide-generator") are
        # very likely to be meaningful list items.
        if "-" in text and len(text) >= 4:
            return "list_item"
        # Otherwise require some length to be classified as list_item
        if len(text) >= 6 and not tl in _GENERIC_TARGET_WORDS:
            return "list_item"

    return "text"


def _element_role(el_type: str) -> str:
    """Derive a semantic role label from element type."""
    return {
        "list_item": "candidate_target",
        "button": "candidate_action",
        "navigation_item": "nav_target",
        "title": "screen_title",
        "status_badge": "status_indicator",
        "error_message": "error_indicator",
        "text": "context_text",
    }.get(el_type, "context_text")


# ---------------------------------------------------------------------------
# App / screen context detection
# ---------------------------------------------------------------------------

# Maps a lowercased keyword to an app context label.
_APP_CONTEXT_HINTS: list[tuple[str, str]] = [
    ("docker desktop", "docker_desktop"),
    ("docker", "docker_desktop"),
    ("containers", "docker_desktop"),
    ("localhost:3000", "webapp_local"),
    ("localhost:", "service_local"),
    ("biblioteca", "biblioteca_app"),
    ("vscode", "vscode"),
    ("visual studio code", "vscode"),
    ("github", "github_web"),
    ("postgresql", "postgresql"),
    ("psql", "postgresql"),
]


def _detect_app_context(ocr_texts: list[str]) -> str | None:
    combined = " ".join(ocr_texts).lower()
    for keyword, label in _APP_CONTEXT_HINTS:
        if keyword in combined:
            return label
    return None


def _detect_screen_title(
    elements: list[dict[str, Any]],
    viewport: dict[str, int],
) -> str | None:
    """Return the most likely screen title from the classified elements."""
    # Prefer explicit title-type elements; skip OCR garbage ([PN, iff, etc.)
    for el in elements:
        label = el["label"]
        if (
            el["type"] == "title"
            and len(label) >= 4
            and "[" not in label
            and "]" not in label
        ):
            return label
    # Fallback: first navigation_item in the upper half of the screen
    vh = viewport["h"]
    for el in elements:
        if el["type"] == "navigation_item" and el["bbox"][1] < vh // 2:
            return el["label"]
    return None


# ---------------------------------------------------------------------------
# Possible actions
# ---------------------------------------------------------------------------


def _infer_actions(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Infer possible user actions from classified UI elements."""
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for el in elements:
        label = el["label"]
        el_type = el["type"]
        conf = el["confidence"]

        # Skip generic / empty targets
        if not label or len(label) < 2:
            continue
        if label.lower().strip() in _GENERIC_TARGET_WORDS:
            continue
        # Deduplicate (case-insensitive)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)

        if el_type in ("button",):
            actions.append(
                {
                    "verb": "CLICK",
                    "target": label,
                    "confidence": round(min(conf * 0.95, 0.95), 3),
                    "reason": "button visible in main area",
                }
            )
        elif el_type == "list_item":
            # Boost hyphenated lowercase identifiers (container names, package
            # names, app IDs like "guide-generator") so they rank above generic
            # words in possible_actions.
            is_hyphen_id = bool(
                re.fullmatch(r"[a-z][a-z0-9]+-[a-z][a-z0-9-]+", label)
            )
            hyphen_boost = 0.07 if is_hyphen_id else 0.0
            actions.append(
                {
                    "verb": "CLICK",
                    "target": label,
                    "confidence": round(min(conf * 0.85 + hyphen_boost, 0.95), 3),
                    "reason": "specific list item in main content"
                    + (" [hyphenated-id]" if is_hyphen_id else ""),
                }
            )
        elif el_type == "navigation_item":
            actions.append(
                {
                    "verb": "CLICK",
                    "target": label,
                    "confidence": round(min(conf * 0.80, 0.85), 3),
                    "reason": "navigation item",
                }
            )
        # title, text, status_badge, error_message → no action inferred

    actions.sort(key=lambda a: -a["confidence"])
    return actions[:8]  # cap at 8


# ---------------------------------------------------------------------------
# Informativeness score
# ---------------------------------------------------------------------------


def _informativeness_score(
    n_total: int,
    n_kept: int,
    elements: list[dict[str, Any]],
    uncertain: bool,
) -> float:
    """Compute a 0–1 informativeness score for a single frame."""
    if n_total == 0 or n_kept == 0:
        return 0.0

    kept_ratio = n_kept / n_total

    typed = [e for e in elements if e["type"] not in ("text",)]
    actionable = [
        e for e in elements
        if e["type"] in ("list_item", "button", "navigation_item", "error_message")
    ]

    typed_bonus = min(len(typed) / max(len(elements), 1) * 0.3, 0.3)
    actionable_bonus = min(len(actionable) / 5.0 * 0.3, 0.3)
    density_bonus = 0.1 if len(elements) >= 4 else 0.0

    score = kept_ratio * 0.3 + typed_bonus + actionable_bonus + density_bonus

    if uncertain:
        score *= 0.7

    return round(min(score, 1.0), 3)


# ---------------------------------------------------------------------------
# Per-frame processing
# ---------------------------------------------------------------------------


def _process_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Transform a single entry from ``analyze_frames.json`` into a facts dict."""
    frame_key: str = frame.get("key") or frame.get("frame_key", "")
    idx: int = int(frame.get("idx", 0))
    t: float = float(frame.get("t", 0.0))

    # Extract raw blocks from OCR data
    ocr_data: dict[str, Any] = frame.get("ocr") or {}
    raw_blocks: list[Any] = ocr_data.get("blocks") or []

    # 1. Normalise blocks
    normalized: list[dict[str, Any]] = []
    for rb in raw_blocks:
        nb = _normalize_block(rb)
        if nb is None:
            continue
        normalized.append(nb)

    n_total = len(normalized)

    # 2. Drop very low-confidence blocks
    low_conf_dropped = 0
    after_conf: list[dict[str, Any]] = []
    for b in normalized:
        if b["confidence"] < _MIN_CONFIDENCE:
            low_conf_dropped += 1
        else:
            after_conf.append(b)

    # 3. Estimate viewport
    viewport = _estimate_viewport(after_conf or normalized)

    # 4. Region filtering
    after_regions, regions_excluded, uncertain = _filter_regions(after_conf, viewport)

    # 5. Noise filtering — track which categories are removed
    kept_blocks: list[dict[str, Any]] = []
    noise_categories_seen: set[str] = set()

    for b in after_regions:
        cat = _noise_category(b["text"])
        if cat is not None:
            noise_categories_seen.add(cat)
        else:
            kept_blocks.append(b)

    if low_conf_dropped > 0:
        noise_categories_seen.add(_CAT_LOW_CONFIDENCE)

    noise_text_removed = sorted(noise_categories_seen)

    n_kept = len(kept_blocks)
    n_dropped = n_total - n_kept

    # 6. Classify remaining blocks into UI elements
    elements: list[dict[str, Any]] = []
    for b in kept_blocks:
        el_type = _element_type(b["text"], b["bbox"], viewport)
        elements.append(
            {
                "label": b["text"],
                "type": el_type,
                "role": _element_role(el_type),
                "confidence": round(b["confidence"], 3),
                "bbox": b["bbox"],
                "source": "ocr",
            }
        )

    # 7. Build main_content_text: sorted by y then x, deduplicated
    seen_texts: set[str] = set()
    ordered = sorted(kept_blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    content_words: list[str] = []
    for b in ordered:
        t_norm = b["text"].strip()
        if t_norm and t_norm not in seen_texts:
            seen_texts.add(t_norm)
            content_words.append(t_norm)
    main_content_text = " ".join(content_words)

    # 8. Detect app context and screen title
    all_ocr_texts = [b["text"] for b in after_conf]
    app_context = _detect_app_context(all_ocr_texts)
    screen_title = _detect_screen_title(elements, viewport)

    # 9. Infer possible actions
    possible_actions = _infer_actions(elements)

    # 10. Informativeness score
    info_score = _informativeness_score(n_total, n_kept, elements, uncertain)

    pct_dropped = round(n_dropped / n_total, 3) if n_total > 0 else 0.0

    return {
        "frame_key": frame_key,
        "idx": idx,
        "t": t,
        "viewport": viewport,
        "app_context": app_context,
        "screen_title": screen_title,
        "regions_excluded": regions_excluded,
        "main_content_text": main_content_text,
        "visible_ui_elements": elements,
        "possible_actions": possible_actions,
        "noise_text_removed": noise_text_removed,
        "informativeness_score": info_score,
        "diagnostics": {
            "n_blocks_total": n_total,
            "n_blocks_kept": n_kept,
            "n_blocks_dropped": n_dropped,
            "pct_dropped": pct_dropped,
            "uncertain": uncertain,
        },
    }


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


async def run(db: AsyncSession, session: Session) -> None:
    """Extract structured visual facts from OCR data.

    Reads ``analyze_frames.json`` (written by either *ocr_frames_local* or
    *analyze_frames*), processes each frame, and writes ``visual_facts.json``.
    """
    if common.stage_done(session, "extract_visual_facts"):
        log.info("extract_visual_facts: already done, skipping")
        return

    session_id = session.id
    log.info("extract_visual_facts: reading analyze_frames artifact [session=%s]", session_id)

    frames_data = common.read_artifact(session_id, "analyze_frames")
    if not frames_data:
        log.warning("extract_visual_facts: no analyze_frames artifact found — skipping")
        return

    if not isinstance(frames_data, list):
        log.error("extract_visual_facts: unexpected artifact format (expected list) — skipping")
        return

    # Process every frame
    processed: list[dict[str, Any]] = []
    for frame in frames_data:
        try:
            fact = _process_frame(frame)
            processed.append(fact)
        except Exception:
            log.exception(
                "extract_visual_facts: error processing frame idx=%s",
                frame.get("idx"),
            )

    # Build summary
    frame_count = len(processed)
    informative_frames = [f for f in processed if f["informativeness_score"] >= 0.2]
    noise_only_frames = [f for f in processed if f["diagnostics"]["n_blocks_kept"] == 0]

    avg_info = (
        round(
            sum(f["informativeness_score"] for f in processed) / frame_count,
            3,
        )
        if frame_count > 0
        else 0.0
    )
    avg_ui_elements = (
        round(
            sum(len(f["visible_ui_elements"]) for f in processed) / frame_count,
            2,
        )
        if frame_count > 0
        else 0.0
    )

    summary: dict[str, Any] = {
        "frame_count": frame_count,
        "informative_frame_count": len(informative_frames),
        "noise_only_frame_count": len(noise_only_frames),
        "avg_informativeness_score": avg_info,
        "avg_ui_elements_per_frame": avg_ui_elements,
    }

    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "frames": processed,
        "summary": summary,
    }

    artifact_key = common.write_artifact(session_id, "visual_facts", payload)
    log.info(
        "extract_visual_facts: wrote %s [frames=%d, informative=%d, avg_score=%.3f]",
        artifact_key,
        frame_count,
        len(informative_frames),
        avg_info,
    )

    await common.record_stage(
        db,
        session,
        stage="extract_visual_facts",
        summary={
            "frame_count": frame_count,
            "informative_frame_count": len(informative_frames),
            "noise_only_frame_count": len(noise_only_frames),
            "avg_informativeness_score": avg_info,
            "avg_ui_elements_per_frame": avg_ui_elements,
            "artifact": artifact_key,
        },
        message=f"extract_visual_facts complete: {frame_count} frames, {len(informative_frames)} informative",
    )
