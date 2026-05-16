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
        events.append(
            {
                "kind": "frame",
                "t": float(f.get("t", 0.0)),
                "frame_key": f.get("key"),
                "ocr_text": ocr_text,
                "ui_summary": f.get("ui_summary", ""),
            }
        )

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
    }
    await common.record_stage(db, session, stage="build_timeline", summary=summary)
