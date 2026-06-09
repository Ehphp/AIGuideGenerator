"""Stage: build_timeline. Pure merge of transcript segments + analyzed frames."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.pipeline import common


def _filter_ocr_by_confidence(frame_entry: dict, conf_min: float) -> str:
    """Return OCR text rebuilt from blocks whose confidence >= conf_min.

    Falls back to the pre-built ``ocr_text`` field when blocks are unavailable
    or ``conf_min`` is 0.0 (disabled).
    """
    raw_text: str = frame_entry.get("ocr_text", "")
    if conf_min <= 0.0:
        return raw_text
    blocks = (frame_entry.get("ocr") or {}).get("blocks") or []
    if not blocks:
        return raw_text
    kept = [
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and float(b.get("confidence", 1.0)) >= conf_min
    ]
    filtered = " ".join(w for w in kept if w.strip())
    # If filtering removed everything, fall back to the full text so the frame
    # is not silently invisible in the timeline.
    return filtered if filtered.strip() else raw_text


async def run(db: AsyncSession, session: Session) -> None:
    if common.stage_done(session, "build_timeline"):
        return

    transcribe_summary = (session.pipeline_artifacts or {}).get("transcribe") or {}
    transcript_full = common.read_artifact(session.id, "transcribe") or {}
    segments = transcript_full.get("segments") or []

    # Prefer the full artifact (has OCR blocks with confidence) over the
    # pipeline_artifacts summary (blocks stripped for DB column size).
    full_analyzed = common.read_artifact(session.id, "analyze_frames") or []
    if not isinstance(full_analyzed, list) or not full_analyzed:
        analyzed_summary = (session.pipeline_artifacts or {}).get("analyze_frames") or []
        full_analyzed = analyzed_summary if isinstance(analyzed_summary, list) else []

    conf_min = settings.ocr_confidence_min

    # Load visual facts produced by extract_visual_facts (optional — graceful
    # fallback when the stage hasn't run or was skipped).
    _VF_TYPES = frozenset(
        {"list_item", "button", "navigation_item", "status_badge", "title", "error_message"}
    )
    _MAX_VF_ELEMENTS = 12

    vf_by_key: dict[str, dict] = {}
    vf_data = common.read_artifact(session.id, "visual_facts")
    if vf_data and isinstance(vf_data, dict):
        for vf_frame in (vf_data.get("frames") or []):
            fk = vf_frame.get("frame_key")
            if fk:
                vf_by_key[fk] = vf_frame
    vf_enriched_count = 0

    # Load parse_screens diagnostic artifact (optional — graceful fallback when
    # the stage hasn't run or was skipped).  Adds screen_type, screen_summary,
    # and ps_important_text (prioritised top-N text labels) to frame events so
    # that downstream LLMs (extract_actions, generate_guide) see a pre-digested,
    # semantically ordered view instead of the positional first-12 slice from
    # visual_facts.
    ps_by_key: dict[str, dict] = {}
    ps_data = common.read_artifact(session.id, "parse_screens")
    if ps_data and isinstance(ps_data, dict):
        for ps_frame in (ps_data.get("frames") or []):
            fk = ps_frame.get("frame_key")
            if fk:
                ps_by_key[fk] = ps_frame
    ps_enriched_count = 0

    events: list[dict] = []
    for seg in segments:
        events.append(
            {
                "kind": "transcript",
                "t": float(seg.get("start", 0.0)),
                "t_end": float(seg.get("end", 0.0)),
                "text": str(seg.get("text", "")).strip(),
            }
        )
    for f in full_analyzed:
        ocr_text = _filter_ocr_by_confidence(f, conf_min)
        frame_key = f.get("key")
        event: dict = {
            "kind": "frame",
            "t": float(f.get("t", 0.0)),
            "frame_key": frame_key,
            "ocr_text": ocr_text,
            "ui_summary": f.get("ui_summary", ""),
        }

        # Enrich with structured visual data when available.
        vf = vf_by_key.get(frame_key) if frame_key else None
        if vf:
            raw_els = vf.get("visible_ui_elements") or []
            event["visual_elements"] = [
                {"label": e["label"], "type": e["type"]}
                for e in raw_els
                if e.get("type") in _VF_TYPES
            ][:_MAX_VF_ELEMENTS]
            event["possible_actions"] = vf.get("possible_actions") or []
            vf_enriched_count += 1

        # Enrich with parse_screens derived data when available.
        # These three fields give downstream LLMs a compact, semantically
        # prioritised representation of the frame content:
        #   screen_type      — coarse UI category (form_page, terminal, etc.)
        #   screen_summary   — one-line summary string
        #   ps_important_text — top-N labels sorted by role, not position
        ps = ps_by_key.get(frame_key) if frame_key else None
        if ps:
            event["screen_type"] = ps.get("screen_type")
            event["screen_summary"] = ps.get("summary")
            important = ps.get("important_text") or []
            if important:
                event["ps_important_text"] = important
            ps_enriched_count += 1

        events.append(event)

    events.sort(key=lambda e: (e["t"], 0 if e["kind"] == "frame" else 1))

    timeline = {
        "language": transcribe_summary.get("language"),
        "events": events,
    }
    common.write_artifact(session.id, "build_timeline", timeline)
    summary = {
        "path": common.artifact_storage_key(session.id, "build_timeline"),
        "event_count": len(events),
        "ocr_confidence_min": conf_min,
        "vf_enriched_frames": vf_enriched_count,
        "ps_enriched_frames": ps_enriched_count,
    }
    await common.record_stage(db, session, stage="build_timeline", summary=summary)
