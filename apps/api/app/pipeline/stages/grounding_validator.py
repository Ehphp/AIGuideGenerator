"""Stage: grounding_validator.

Deterministic post-generation audit stage.  Reads the validated Guide
(``session.guide_content``) and cross-references every step's actions
against the raw ``build_timeline`` OCR text and transcript text.

Zero LLM calls.  Zero image loading.  Zero mutations to ``guide_content``.

Produces
--------
``guide_grounding_report.json``
    Full per-step grounding detail, written to the session artifact dir.

``pipeline_artifacts["grounding_validator"]``
    Aggregate metrics only (no per-step text), safe to expose via the API.

Metrics emitted
---------------
visual_grounding_rate
    Fraction of steps whose CLICK/TYPE/SELECT action targets are found in
    nearby frame OCR text.

audio_dependency_score
    Fraction of steps whose targets are found in transcript events but NOT
    in frame OCR.

unverified_action_rate
    Fraction of actions whose target is found in NEITHER OCR nor transcript.

target_verification_rate
    Fraction of actions whose target appears verbatim (or as a token
    intersection) in nearby frame OCR text.

step_source_distribution
    Breakdown by grounding_status: grounded / audio_only / unverified /
    no_actions.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.pipeline import common
from app.schemas.guide import Guide

log = logging.getLogger(__name__)

# Temporal window for evidence lookup.  Asymmetric: narration often comes
# after the UI state that motivates the action is already on screen.
_PRE_ACTION_WINDOW_SEC: float = 30.0   # look back before step t_start
_POST_ACTION_WINDOW_SEC: float = 10.0  # look forward past step t_end

# Minimum token length for matching.  Kept at 2 so short labels like
# "OK", "No", "ID" are not silently excluded.
_MIN_TOKEN_LEN: int = 2

# Generic UI label vocabulary.  Targets composed exclusively of these tokens
# are likely LLM paraphrases rather than verbatim labels from the screen.
_GENERIC_TARGETS: frozenset[str] = frozenset({
    "button", "search button", "search field", "container",
    "menu", "field", "item", "option", "link", "result",
    "page", "tab", "icon", "input", "form", "list",
    "checkbox", "dropdown", "select", "text", "label",
    "element", "panel", "section", "area", "box",
    "dialog", "modal", "window", "header", "footer",
    "bar", "row", "column", "cell", "card",
    "submit", "close", "cancel", "confirm",
    "image", "video", "file", "folder", "document",
    "next", "back", "previous", "continue", "finish",
})

# Tokens to skip when extracting candidate visual targets from OCR.
_OCR_NOISE_TOKENS: frozenset[str] = frozenset({
    # English stop-words / filler
    "the", "and", "for", "with", "this", "that", "from", "into",
    "not", "new", "only", "show", "all", "more", "last", "ago",
    "days", "hours", "months",
    # Italian stop-words (common in test sessions)
    "il", "la", "le", "di", "da", "in", "su", "un", "una", "del",
    # Tech / log noise
    "get", "http", "https", "200", "ok", "local", "host",
    "localhost", "www", "com", "net", "org", "signed", "available",
    "version", "started", "selected", "usage", "cpus", "ram",
    "cpu", "port", "ports", "running", "exited", "created",
})


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Return lowercase word-tokens of length >= _MIN_TOKEN_LEN."""
    return {
        w.lower().strip(".,;:()[]{}\"'/-_")
        for w in text.split()
        if len(w.strip(".,;:()[]{}\"'/-_")) >= _MIN_TOKEN_LEN
    }


def _is_generic_target(target: str) -> bool:
    """Return True if *target* is composed entirely of generic UI vocabulary.

    Generic targets are LLM-invented labels (e.g. "Search Button",
    "Container") rather than verbatim text lifted from the screen.
    """
    if not target:
        return False
    t_lower = target.lower().strip()
    if t_lower in _GENERIC_TARGETS:
        return True
    tokens = _tokenize(target)
    return bool(tokens) and tokens.issubset(_GENERIC_TARGETS)


def _extract_candidate_targets(
    frame_events: list[dict], max_candidates: int = 6
) -> list[str]:
    """Extract meaningful visual target candidates from nearby OCR frames.

    Prioritises hyphenated compound identifiers (e.g. ``guide-generator``,
    ``problemi-db``) over plain tokens, then ranks by frequency.  Skips
    noise tokens, generic UI words, colons (Docker image tags / ports), and
    hex hashes.
    """
    if not frame_events:
        return []

    counts: Counter[str] = Counter()
    for ev in frame_events:
        raw = (ev.get("ocr_text") or "") + " " + (ev.get("ui_summary") or "")
        for word in raw.split():
            clean = word.strip(".,;:()[]{}\"'/@\u00a9*#|\u2026<>")
            if not clean or len(clean) < 3:
                continue
            # Skip tokens that start or end with a hyphen (partial/truncated OCR reads).
            if clean.startswith("-") or clean.endswith("-"):
                continue
            cl = clean.lower()
            if ":" in cl or "/" in cl:               # ports, URLs, image tags, paths
                continue
            # Skip date patterns (YYYY-MM-DD, YYYY-YYYY) and pure numeric sequences.
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cl) or re.fullmatch(r"\d{4}-\d{4}", cl):
                continue
            if cl.isdigit() or re.fullmatch(r"[0-9a-f]{8,}", cl):  # numbers / hex IDs
                continue
            if cl.startswith("http") or cl.startswith("www"):
                continue
            # Skip document-title slugs: CamelCase-and-CamelCase patterns
            # (browser tab titles for open documents, e.g. "Viewing-and-Managing-D").
            if re.search(r"[A-Z][a-z]+-and-[A-Z]", clean):
                continue
            if cl in _OCR_NOISE_TOKENS or cl in _GENERIC_TARGETS:
                continue
            counts[clean] += 1

    # Prefer hyphenated identifiers (almost always meaningful app/container names).
    candidates = sorted(
        counts.keys(),
        key=lambda w: (0 if "-" in w else 1, -counts[w]),
    )
    return candidates[:max_candidates]


def _events_in_window(
    events: list[dict],
    t_start: float | None,
    t_end: float | None,
    pre_sec: float = _PRE_ACTION_WINDOW_SEC,
    post_sec: float = _POST_ACTION_WINDOW_SEC,
) -> tuple[list[dict], list[dict]]:
    """Return (frame_events, transcript_events) near [t_start, t_end].

    Uses an *asymmetric* window: ``pre_sec`` seconds before ``t_start`` and
    ``post_sec`` seconds after ``t_end``.  The wider pre-action lookback
    captures UI states displayed before the narration begins.

    When no timing info is available, all events are returned as a
    conservative fallback so grounding is never silently skipped.
    """
    if t_start is None and t_end is None:
        frame_ev = [e for e in events if e.get("kind") == "frame"]
        trans_ev = [e for e in events if e.get("kind") == "transcript"]
        return frame_ev, trans_ev

    t_ref_lo = t_start if t_start is not None else t_end
    t_ref_hi = t_end if t_end is not None else t_start
    lo = t_ref_lo - pre_sec   # type: ignore[operator]
    hi = t_ref_hi + post_sec  # type: ignore[operator]

    frame_ev: list[dict] = []
    trans_ev: list[dict] = []
    for e in events:
        t = float(e.get("t", 0.0))
        if lo <= t <= hi:
            if e.get("kind") == "frame":
                frame_ev.append(e)
            elif e.get("kind") == "transcript":
                trans_ev.append(e)
    return frame_ev, trans_ev


def _all_frame_events(events: list[dict]) -> list[dict]:
    """Return all frame events in the session (for temporal-miss detection)."""
    return [e for e in events if e.get("kind") == "frame"]


def _nearest_frame_distance(
    target: str, all_frames: list[dict], t_ref: float | None
) -> float | None:
    """Return seconds between t_ref and the nearest frame containing *target*.

    Returns None if *target* is not found in any frame.
    """
    if t_ref is None or not target or not all_frames:
        return None
    t_lower = target.lower().strip()
    target_tokens = _tokenize(target)
    best: float | None = None
    for ev in all_frames:
        ocr = (ev.get("ocr_text") or "") + " " + (ev.get("ui_summary") or "")
        ocr_lower = ocr.lower()
        match = (t_lower in ocr_lower) or (bool(target_tokens & _tokenize(ocr)))
        if match:
            dist = abs(float(ev.get("t", 0.0)) - t_ref)
            if best is None or dist < best:
                best = dist
    return round(best, 2) if best is not None else None


def _target_in_ocr(target: str, frame_events: list[dict]) -> tuple[bool, float]:
    """Return (found, confidence) where confidence = hit_rate across frames.

    Matching strategy (either condition is sufficient):
    1. Case-insensitive verbatim substring of the full OCR text.
    2. At least one token from *target* appears in the frame's OCR tokens.
    """
    if not target or not frame_events:
        return False, 0.0
    t_lower = target.lower().strip()
    target_tokens = _tokenize(target)
    if not target_tokens and not t_lower:
        return False, 0.0

    hits = 0
    for ev in frame_events:
        ocr = (ev.get("ocr_text") or "") + " " + (ev.get("ui_summary") or "")
        ocr_lower = ocr.lower()
        if t_lower in ocr_lower:
            hits += 1
            continue
        if target_tokens and bool(target_tokens & _tokenize(ocr)):
            hits += 1
    if hits == 0:
        return False, 0.0
    return True, round(hits / len(frame_events), 3)


def _target_in_transcript(
    target: str,
    transcript_events: list[dict],
    transcript_excerpt: str,
) -> bool:
    """Return True if any token of *target* appears in nearby transcript text."""
    if not target:
        return False
    t_lower = target.lower().strip()
    target_tokens = _tokenize(target)
    if not target_tokens and not t_lower:
        return False

    # Check the LLM-generated excerpt first (fast).
    if transcript_excerpt and t_lower in transcript_excerpt.lower():
        return True
    if transcript_excerpt and target_tokens & _tokenize(transcript_excerpt):
        return True

    # Check nearby raw transcript events from the timeline.
    all_text = " ".join(ev.get("text", "") for ev in transcript_events)
    if not all_text:
        return False
    if t_lower in all_text.lower():
        return True
    return bool(target_tokens & _tokenize(all_text))


# ---------------------------------------------------------------------------
# Per-step grounding
# ---------------------------------------------------------------------------


def _classify_step(step_dict: dict, events: list[dict]) -> dict[str, Any]:
    """Return grounding detail dict for one step."""
    evidence = step_dict.get("evidence") or {}
    t_start = evidence.get("t_start")
    t_end = evidence.get("t_end")
    transcript_excerpt = evidence.get("transcript_excerpt") or ""
    actions = step_dict.get("actions") or []
    # Reference timestamp for distance calculations (prefer t_start).
    t_ref = t_start if t_start is not None else t_end

    # Primary asymmetric window.
    frame_ev, trans_ev = _events_in_window(events, t_start, t_end)
    has_nearby_frames = bool(frame_ev)

    # Full-session frames (for temporal-miss detection).
    all_frames = _all_frame_events(events)

    # Candidate targets from nearby frames (shared across all actions in step).
    nearby_candidates = _extract_candidate_targets(frame_ev)

    action_results: list[dict] = []
    for action in actions:
        target = action.get("target") or ""
        verb = action.get("verb") or ""
        is_generic = _is_generic_target(target)
        in_ocr, ocr_conf = _target_in_ocr(target, frame_ev)
        in_trans = _target_in_transcript(target, trans_ev, transcript_excerpt)

        # Temporal-miss: visible in session but outside the primary window.
        # Only meaningful for specific (non-generic) targets; generic words
        # like "button" or "field" appear in browser chrome everywhere.
        found_outside_window = False
        nearest_distance: float | None = None
        if not in_ocr and not is_generic:
            nearest_distance = _nearest_frame_distance(target, all_frames, t_ref)
            found_outside_window = nearest_distance is not None

        a_result: dict[str, Any] = {
            "verb": verb,
            "target": target,
            "is_generic": is_generic,
            "found_in_ocr": in_ocr,
            "found_in_transcript": in_trans,
            "ocr_confidence": ocr_conf,
        }
        if nearest_distance is not None:
            a_result["nearest_match_distance_sec"] = nearest_distance
        if found_outside_window:
            a_result["found_outside_window"] = True
        if nearby_candidates:
            a_result["suggested_visual_targets"] = nearby_candidates
        action_results.append(a_result)

    # ------------------------------------------------------------------
    # Step-level provenance and grounding status
    # ------------------------------------------------------------------
    if not actions:
        provenance = "no_actions"
        visual_confidence = 0.0
        audio_confidence = 1.0 if (trans_ev or transcript_excerpt) else 0.0
        grounding_status = "no_actions"
    else:
        n = len(actions)
        # Non-generic OCR hits = confirmed visual grounding.
        ocr_non_generic = sum(
            1 for a in action_results if a["found_in_ocr"] and not a["is_generic"]
        )
        # Generic OCR hits = word appeared but match may be coincidental.
        ocr_generic = sum(
            1 for a in action_results if a["found_in_ocr"] and a["is_generic"]
        )
        trans_hits = sum(1 for a in action_results if a["found_in_transcript"])
        temporal_miss = sum(
            1 for a in action_results if a.get("found_outside_window")
        )
        all_generic = all(a["is_generic"] for a in action_results)

        visual_confidence = round((ocr_non_generic + ocr_generic) / n, 3)
        audio_confidence = round(trans_hits / n, 3)

        if ocr_non_generic > 0 and trans_hits > 0:
            provenance = "audio+visual"
        elif ocr_non_generic > 0:
            provenance = "visual"
        elif trans_hits > 0:
            provenance = "audio_only"
        else:
            provenance = "inferred"

        # Grounding status (most-specific condition checked first).
        if ocr_non_generic > 0:
            grounding_status = "grounded"
        elif ocr_generic > 0:
            # Found in OCR but only via generic-word overlap — uncertain.
            grounding_status = "weak_visual"
        elif all_generic:
            # LLM used a generic label; may or may not have been on screen.
            grounding_status = "generic_target"
        elif temporal_miss > 0:
            # Specific target is in the session OCR but at a different time.
            grounding_status = "possible_temporal_miss"
        elif trans_hits > 0:
            grounding_status = "audio_only"
        else:
            grounding_status = "unverified"

    needs_review = grounding_status in (
        "audio_only", "unverified", "generic_target", "possible_temporal_miss"
    ) and bool(actions)

    result: dict[str, Any] = {
        "step_id": step_dict.get("id"),
        "step_order": step_dict.get("order"),
        "title": step_dict.get("title"),
        "t_start": t_start,
        "t_end": t_end,
        "nearby_frame_events": len(frame_ev),
        "nearby_transcript_events": len(trans_ev),
        "has_nearby_frames": has_nearby_frames,
        "actions": action_results,
        "source_provenance": provenance,
        "visual_confidence": visual_confidence,
        "audio_confidence": audio_confidence,
        "grounding_status": grounding_status,
        "needs_review": needs_review,
    }

    # Diagnostic lists (appended only when non-empty).
    ocr_matched = [
        a["target"] for a in action_results if a["found_in_ocr"] and not a["is_generic"]
    ]
    if ocr_matched:
        result["ocr_matched_targets"] = ocr_matched

    generic_found = [a["target"] for a in action_results if a["is_generic"]]
    if generic_found:
        result["generic_targets"] = generic_found

    unverified_targets = [
        a["target"]
        for a in action_results
        if not a["found_in_ocr"] and not a["found_in_transcript"] and not a["is_generic"]
    ]
    if unverified_targets:
        result["unverified_targets"] = unverified_targets

    outside_window = [
        a["target"] for a in action_results if a.get("found_outside_window")
    ]
    if outside_window:
        result["outside_window_targets"] = outside_window

    return result


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "grounding_validator"):
        return

    if not session.guide_content:
        raise RuntimeError(
            "grounding_validator requires guide_content to be set by validate_guide"
        )

    # Use the raw (pre-sanitization) build_timeline: it has full OCR text and
    # transcript text, whereas sanitize_timeline has PII replaced with placeholders.
    # Both are local-only artifacts; the grounding validator never sends data outside.
    timeline = common.read_artifact(session.id, "build_timeline")
    if not timeline:
        raise RuntimeError("grounding_validator requires build_timeline artifact")

    events: list[dict] = timeline.get("events") or []
    guide = Guide.model_validate(session.guide_content)

    # ------------------------------------------------------------------
    # Non-procedural short-circuit: if the document has no steps (e.g., a
    # technical or conceptual doc), UI-action grounding is not meaningful.
    # Record a clear marker and exit without producing misleading metrics.
    # ------------------------------------------------------------------
    if not guide.steps:
        doc_type = guide.document_type or "unknown"
        skipped_summary: dict[str, Any] = {
            "path": common.artifact_storage_key(session.id, "guide_grounding_report"),
            "grounding_skipped": True,
            "reason": "no_steps",
            "document_type": doc_type,
            # Zero-valued metrics so consumers that read these fields don't break.
            "strict_visual_grounding_rate": 0.0,
            "weak_visual_grounding_rate": 0.0,
            "visual_grounding_rate": 0.0,
            "audio_dependency_score": 0.0,
            "unverified_action_rate": 0.0,
            "target_verification_rate": 0.0,
            "generic_target_rate": 0.0,
            "possible_temporal_miss_rate": 0.0,
            "visual_candidate_count": 0,
            "step_source_distribution": {},
            "steps_needing_review": 0,
            "total_steps": 0,
            "total_actions": 0,
        }
        skipped_report: dict[str, Any] = {
            "schema_version": "1.1",
            "session_id": str(session.id),
            "grounding_skipped": True,
            "reason": "no_steps — document_type is non-procedural",
            "document_type": doc_type,
            "summary": skipped_summary,
            "steps": [],
        }
        common.write_artifact(session.id, "guide_grounding_report", skipped_report)
        await common.record_stage(
            db,
            session,
            stage="grounding_validator",
            summary=skipped_summary,
            message=(
                f"grounding_validator: skipped (document_type={doc_type}, no steps to ground)"
            ),
        )
        log.info(
            "grounding_validator: skipped — document_type=%s, no steps (session=%s)",
            doc_type,
            session.id,
        )
        return

    step_reports: list[dict] = []
    for step in guide.steps:
        report = _classify_step(step.model_dump(), events)
        step_reports.append(report)

    # -----------------------------------------------------------------------
    # Aggregate metrics
    # -----------------------------------------------------------------------
    total = len(step_reports)
    grounded = sum(1 for r in step_reports if r["grounding_status"] == "grounded")
    weak_visual = sum(1 for r in step_reports if r["grounding_status"] == "weak_visual")
    audio_only = sum(1 for r in step_reports if r["grounding_status"] == "audio_only")
    unverified = sum(1 for r in step_reports if r["grounding_status"] == "unverified")
    generic_target_steps = sum(
        1 for r in step_reports if r["grounding_status"] == "generic_target"
    )
    temporal_miss_steps = sum(
        1 for r in step_reports if r["grounding_status"] == "possible_temporal_miss"
    )
    no_actions = sum(1 for r in step_reports if r["grounding_status"] == "no_actions")
    needs_review_count = sum(1 for r in step_reports if r.get("needs_review"))

    all_actions = [a for r in step_reports for a in (r.get("actions") or [])]
    n_actions = len(all_actions)

    strict_visual_grounding_rate = round(grounded / total, 3) if total else 0.0
    weak_visual_grounding_rate = round(weak_visual / total, 3) if total else 0.0
    visual_grounding_rate = strict_visual_grounding_rate  # backward-compat alias
    audio_dependency_score = (
        round((audio_only + unverified + generic_target_steps) / total, 3)
        if total
        else 0.0
    )
    unverified_action_rate = (
        round(
            sum(
                1
                for a in all_actions
                if not a["found_in_ocr"] and not a["found_in_transcript"]
            )
            / n_actions,
            3,
        )
        if n_actions
        else 0.0
    )
    target_verification_rate = (
        round(
            sum(1 for a in all_actions if a["found_in_ocr"] and not a.get("is_generic"))
            / n_actions,
            3,
        )
        if n_actions
        else 0.0
    )
    generic_target_rate = (
        round(sum(1 for a in all_actions if a.get("is_generic")) / n_actions, 3)
        if n_actions
        else 0.0
    )
    possible_temporal_miss_rate = round(temporal_miss_steps / total, 3) if total else 0.0

    # Unique visual candidates suggested across all actions.
    all_candidates: set[str] = set()
    for r in step_reports:
        for a in r.get("actions") or []:
            for c in a.get("suggested_visual_targets") or []:
                all_candidates.add(c)
    visual_candidate_count = len(all_candidates)

    summary_metrics: dict[str, Any] = {
        # Primary grounding signals
        "strict_visual_grounding_rate": strict_visual_grounding_rate,
        "weak_visual_grounding_rate": weak_visual_grounding_rate,
        "visual_grounding_rate": visual_grounding_rate,  # backward-compat alias
        "audio_dependency_score": audio_dependency_score,
        # Action-level rates
        "unverified_action_rate": unverified_action_rate,
        "target_verification_rate": target_verification_rate,
        "generic_target_rate": generic_target_rate,
        "possible_temporal_miss_rate": possible_temporal_miss_rate,
        # Discovery
        "visual_candidate_count": visual_candidate_count,
        # Distribution
        "step_source_distribution": {
            "grounded": grounded,
            "weak_visual": weak_visual,
            "audio_only": audio_only,
            "unverified": unverified,
            "generic_target": generic_target_steps,
            "possible_temporal_miss": temporal_miss_steps,
            "no_actions": no_actions,
        },
        "steps_needing_review": needs_review_count,
        "total_steps": total,
        "total_actions": n_actions,
    }

    full_report: dict[str, Any] = {
        "schema_version": "1.1",
        "session_id": str(session.id),
        "pre_action_window_sec": _PRE_ACTION_WINDOW_SEC,
        "post_action_window_sec": _POST_ACTION_WINDOW_SEC,
        "summary": summary_metrics,
        "steps": step_reports,
    }

    common.write_artifact(session.id, "guide_grounding_report", full_report)

    db_summary: dict[str, Any] = {
        "path": common.artifact_storage_key(session.id, "guide_grounding_report"),
        **summary_metrics,
    }
    await common.record_stage(
        db,
        session,
        stage="grounding_validator",
        summary=db_summary,
        message=(
            f"grounding: {total} steps, grounded={grounded}, weak_visual={weak_visual}, "
            f"generic_target={generic_target_steps}, audio_only={audio_only}, "
            f"unverified={unverified}, strict_vgr={strict_visual_grounding_rate:.2f}"
        ),
    )

    log.info(
        "grounding_validator: steps=%d grounded=%d audio_only=%d unverified=%d "
        "visual_grounding_rate=%.2f audio_dependency=%.2f (session=%s)",
        total,
        grounded,
        audio_only,
        unverified,
        visual_grounding_rate,
        audio_dependency_score,
        session.id,
    )
