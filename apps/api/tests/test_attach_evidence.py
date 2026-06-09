"""Tests for the deterministic evidence-attachment logic (Phase F).

All tests use the pure functions from ``app.pipeline.evidence`` directly,
keeping the test suite fast and free of DB/I/O dependencies.

The pipeline-integration test at the bottom uses the stage wrapper with a
lightweight fake session.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipeline.evidence import (
    attach_missing_click_evidence,
    choose_nearest_frame_for_step,
    guide_has_opacified_keys,
    step_has_click,
    valid_frame_keys,
)
from app.schemas.guide import Action, Evidence, Guide, GuideMetadata, Step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(
    *,
    verb: str = "CLICK",
    target: str = "Button",
    frame_keys: list[str] | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    frame_source: str | None = None,
    frame_distance_sec: float | None = None,
) -> Step:
    return Step(
        id="step-1",
        order=1,
        title="Test Step",
        description="A test step.",
        actions=[Action(verb=verb, target=target)],
        evidence=Evidence(
            frame_keys=frame_keys or [],
            t_start=t_start,
            t_end=t_end,
            frame_source=frame_source,
            frame_distance_sec=frame_distance_sec,
        ),
        confidence=0.8,
    )


def _make_guide(steps: list[Step]) -> Guide:
    return Guide(
        title="Test Guide",
        summary="A guide.",
        steps=steps,
        metadata=GuideMetadata(),
    )


def _frames(*timestamps: float, session_id: str = "sid") -> list[dict]:
    """Build a minimal extract_frames list from a sequence of timestamps."""
    return [
        {"idx": i, "t": float(t), "key": f"sessions/{session_id}/frames/frame_{i:04d}.jpg"}
        for i, t in enumerate(timestamps)
    ]


# ---------------------------------------------------------------------------
# step_has_click
# ---------------------------------------------------------------------------

def test_step_has_click_true():
    step = _make_step(verb="CLICK")
    assert step_has_click(step) is True


def test_step_has_click_false():
    step = _make_step(verb="VERIFY")
    assert step_has_click(step) is False


def test_step_has_click_mixed_actions():
    step = Step(
        id="s",
        order=1,
        title="T",
        description="D",
        actions=[
            Action(verb="NAVIGATE", target="Settings"),
            Action(verb="CLICK", target="Save"),
        ],
        evidence=Evidence(),
        confidence=0.8,
    )
    assert step_has_click(step) is True


# ---------------------------------------------------------------------------
# valid_frame_keys
# ---------------------------------------------------------------------------

def test_valid_frame_keys_filters_unknown():
    available = {"sessions/sid/frames/frame_0001.jpg", "sessions/sid/frames/frame_0002.jpg"}
    result = valid_frame_keys(
        ["sessions/sid/frames/frame_0001.jpg", "sessions/sid/frames/frame_FAKE.jpg"],
        available,
    )
    assert result == ["sessions/sid/frames/frame_0001.jpg"]


def test_valid_frame_keys_all_valid():
    available = {"a.jpg", "b.jpg"}
    assert valid_frame_keys(["a.jpg", "b.jpg"], available) == ["a.jpg", "b.jpg"]


def test_valid_frame_keys_empty_input():
    assert valid_frame_keys([], {"a.jpg"}) == []


def test_valid_frame_keys_empty_available():
    assert valid_frame_keys(["a.jpg"], set()) == []


def test_valid_frame_keys_resolves_opacified_stem():
    """Opacified key 'frame_0001' produced by prepare_for_egress must resolve
    back to the full storage path."""
    available = {
        "sessions/abc123/frames/frame_0001.jpg",
        "sessions/abc123/frames/frame_0002.jpg",
    }
    result = valid_frame_keys(["frame_0001", "frame_0003"], available)
    assert result == ["sessions/abc123/frames/frame_0001.jpg"]


# ---------------------------------------------------------------------------
# choose_nearest_frame_for_step
# ---------------------------------------------------------------------------

class TestChooseNearestFrame:

    def test_in_range_closest_to_tstart(self):
        """Canonical example: t_start=36, t_end=47, frames at 34/37/41 → 37."""
        step = _make_step(t_start=36.0, t_end=47.0)
        frames = _frames(34.0, 37.0, 41.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 37.0

    def test_in_range_single_candidate(self):
        step = _make_step(t_start=10.0, t_end=20.0)
        frames = _frames(5.0, 15.0, 30.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 15.0

    def test_no_in_range_prefers_post_action_over_pre_action(self):
        """Rule 4b: when no frame falls in [t_start, t_end], the first frame
        after t_end (within max_nearest_sec × 5) is preferred over a
        pre-action frame that is closer in raw seconds.  This ensures that
        navigation/CLICK steps show the destination state rather than the
        transient pre-click state.
        """
        step = _make_step(t_start=20.0, t_end=25.0)
        # t=18 is 2 s before t_start (pre-action); t=30 is 5 s after t_end (post-action).
        # Rule 4b fires first and returns the post-action frame.
        frames = _frames(5.0, 18.0, 30.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 30.0

    def test_no_in_range_post_action_within_window(self):
        """Rule 4b: only a post-action candidate exists (no frame in range,
        no pre-action frame within max_nearest_sec).  Returns the post-action
        frame when it is within max_nearest_sec × 5 past t_end.
        """
        step = _make_step(t_start=20.0, t_end=25.0)
        # t=5 is far (15 s from t_start), t=30 is 5 s post t_end → Rule 4b picks 30.
        frames = _frames(5.0, 30.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 30.0

    def test_no_frame_in_range_or_post_window_returns_none(self):
        """No frame in range, no frame within max_nearest_sec of t_start, and
        no post-action frame within the 5× window → must return None.
        """
        step = _make_step(t_start=20.0, t_end=25.0)
        # t=5 only — 15 s from t_start, 20 s from t_end; both too far.
        frames = _frames(5.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is None

    def test_only_t_start_no_range(self):
        step = _make_step(t_start=10.0)
        frames = _frames(8.0, 12.0, 20.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 8.0  # nearest to t_start=10 → |8-10|=2, |12-10|=2 → first wins

    def test_only_t_end_as_fallback(self):
        step = _make_step(t_end=15.0)
        frames = _frames(12.0, 20.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 12.0  # |12-15|=3 ≤ 3.0

    def test_no_timestamps_returns_none(self):
        step = _make_step()  # no t_start, no t_end
        frames = _frames(10.0, 20.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is None

    def test_empty_frames_returns_none(self):
        step = _make_step(t_start=10.0, t_end=20.0)
        chosen = choose_nearest_frame_for_step(step, [], max_nearest_sec=3.0)
        assert chosen is None

    def test_boundary_inclusive(self):
        """Frames exactly at t_start and t_end are considered in-range."""
        step = _make_step(t_start=36.0, t_end=47.0)
        frames = _frames(36.0, 47.0)
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 36.0  # both in range; 36 is closer to t_start

    def test_threshold_boundary_exact(self):
        """Frame at exactly max_nearest_sec distance is accepted."""
        step = _make_step(t_start=10.0)
        frames = _frames(13.0)  # distance = 3.0 exactly
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is not None
        assert chosen["t"] == 13.0

    def test_threshold_boundary_exceeded(self):
        """Frame at max_nearest_sec + epsilon is rejected."""
        step = _make_step(t_start=10.0)
        frames = _frames(13.1)  # distance = 3.1 > 3.0
        chosen = choose_nearest_frame_for_step(step, frames, max_nearest_sec=3.0)
        assert chosen is None


# ---------------------------------------------------------------------------
# attach_missing_click_evidence
# ---------------------------------------------------------------------------

class TestAttachMissingClickEvidence:

    # 1. Step with CLICK, empty evidence, frame inside range → assigned
    def test_assigns_frame_when_evidence_empty(self):
        sid = str(uuid.uuid4())
        step = _make_step(t_start=36.0, t_end=47.0)
        guide = _make_guide([step])
        frames = [
            {"idx": 0, "t": 34.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 37.0, "key": f"sessions/{sid}/frames/frame_0001.jpg"},
            {"idx": 2, "t": 41.0, "key": f"sessions/{sid}/frames/frame_0002.jpg"},
        ]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == [f"sessions/{sid}/frames/frame_0001.jpg"]
        assert result.steps[0].evidence.frame_source == "nearest_frame"
        assert result.steps[0].evidence.frame_distance_sec == 1.0

    # 2. Canonical example: t_start=36, t_end=47, frames 34/37/41 → 37
    def test_canonical_example(self):
        sid = "test-session"
        step = _make_step(t_start=36.0, t_end=47.0)
        guide = _make_guide([step])
        frames = [
            {"idx": 0, "t": 34.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 37.0, "key": f"sessions/{sid}/frames/frame_0001.jpg"},
            {"idx": 2, "t": 41.0, "key": f"sessions/{sid}/frames/frame_0002.jpg"},
        ]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == ["sessions/test-session/frames/frame_0001.jpg"]

    # 3. No frame in range but nearby within 3s → nearest assigned
    def test_nearest_fallback_when_no_in_range(self):
        sid = "s"
        step = _make_step(t_start=20.0, t_end=25.0)
        frames = [{"idx": 0, "t": 18.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(guide=_make_guide([step]), frames=frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == [f"sessions/{sid}/frames/frame_0000.jpg"]
        assert result.steps[0].evidence.frame_source == "nearest_frame"
        assert result.steps[0].evidence.frame_distance_sec == 2.0

    # 4. No frame within 3s → evidence stays empty
    def test_no_frame_within_threshold_leaves_empty(self):
        step = _make_step(t_start=20.0, t_end=25.0)
        frames = [{"idx": 0, "t": 5.0, "key": "sessions/s/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"

    # 5. Step without CLICK → evidence not touched
    def test_non_click_step_not_modified(self):
        step = _make_step(verb="VERIFY")
        guide = _make_guide([step])
        frames = [{"idx": 0, "t": 0.0, "key": "sessions/s/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source is None  # untouched

    # 6. Step already has valid frame_keys → not overwritten
    def test_does_not_overwrite_valid_evidence(self):
        sid = "s"
        existing_key = f"sessions/{sid}/frames/frame_0001.jpg"
        step = _make_step(
            t_start=10.0, t_end=20.0,
            frame_keys=[existing_key],
        )
        frames = [
            {"idx": 0, "t": 12.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 15.0, "key": existing_key},
        ]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == [existing_key]
        assert result.steps[0].evidence.frame_source == "llm"

    # 7. Hallucinated (invalid) frame_keys → replaced with valid nearest
    def test_replaces_hallucinated_keys_with_nearest(self):
        sid = "s"
        valid_key = f"sessions/{sid}/frames/frame_0001.jpg"
        step = _make_step(
            t_start=10.0, t_end=20.0,
            frame_keys=["sessions/s/frames/INVENTED_KEY.jpg"],
        )
        frames = [{"idx": 1, "t": 11.0, "key": valid_key}]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == [valid_key]
        assert result.steps[0].evidence.frame_source == "nearest_frame"

    # 8. Hallucinated keys + no nearby frame → evidence cleared, no crash
    def test_replaces_hallucinated_keys_no_nearby_no_crash(self):
        step = _make_step(
            t_start=10.0, t_end=20.0,
            frame_keys=["sessions/s/frames/INVENTED.jpg"],
        )
        frames = [{"idx": 0, "t": 50.0, "key": "sessions/s/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"

    # 9. Backward compatibility: guide without new fields validates fine
    def test_backward_compat_old_evidence_no_provenance_fields(self):
        raw = {
            "schema_version": "1.0",
            "title": "Old Guide",
            "summary": "s",
            "steps": [
                {
                    "id": "step-1",
                    "order": 1,
                    "title": "T",
                    "description": "D",
                    "actions": [{"verb": "CLICK", "target": "Btn", "value": None}],
                    "evidence": {
                        "frame_keys": [],
                        "transcript_excerpt": "",
                        "t_start": None,
                        "t_end": None,
                        # frame_source and frame_distance_sec absent
                    },
                    "warnings": [],
                    "notes": [],
                    "confidence": 0.7,
                }
            ],
            "warnings": [],
            "notes": [],
        }
        guide = Guide.model_validate(raw)
        assert guide.steps[0].evidence.frame_source is None
        assert guide.steps[0].evidence.frame_distance_sec is None

    # 10. Idempotency: running twice yields same result
    def test_idempotent(self):
        sid = "s"
        step = _make_step(t_start=36.0, t_end=47.0)
        guide = _make_guide([step])
        frames = [
            {"idx": 0, "t": 34.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 37.0, "key": f"sessions/{sid}/frames/frame_0001.jpg"},
        ]
        result_first = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        keys_after_first = list(result_first.steps[0].evidence.frame_keys)
        source_after_first = result_first.steps[0].evidence.frame_source

        result_second = attach_missing_click_evidence(result_first, frames, max_nearest_sec=3.0)
        assert result_second.steps[0].evidence.frame_keys == keys_after_first
        assert result_second.steps[0].evidence.frame_source == source_after_first

    # 11. frame_source preserved on second run (idempotency of LLM tag)
    def test_idempotent_preserves_llm_source(self):
        sid = "s"
        valid_key = f"sessions/{sid}/frames/frame_0000.jpg"
        step = _make_step(frame_keys=[valid_key], frame_source="llm")
        frames = [{"idx": 0, "t": 5.0, "key": valid_key}]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_source == "llm"

    # 12. Mixed steps: only CLICK steps are touched
    def test_mixed_steps_only_click_touched(self):
        sid = "s"
        click_step = _make_step(verb="CLICK", t_start=10.0, t_end=20.0)
        verify_step = _make_step(verb="VERIFY", t_start=25.0, t_end=30.0)
        guide = _make_guide([click_step, verify_step])
        frames = [
            {"idx": 0, "t": 12.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
        ]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        # CLICK step gets evidence
        assert result.steps[0].evidence.frame_keys != []
        assert result.steps[0].evidence.frame_source == "nearest_frame"
        # VERIFY step untouched
        assert result.steps[1].evidence.frame_keys == []
        assert result.steps[1].evidence.frame_source is None

    # 13. Frames missing 't' key → no crash, treated as if no frames available
    def test_frames_missing_t_key_no_crash(self):
        step = _make_step(t_start=10.0, t_end=20.0)
        # All frames are missing the 't' field — should not crash
        frames = [{"idx": 0, "key": "sessions/s/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"

    # 14. Frames missing 'key' field → no crash, treated as if no frames available
    def test_frames_missing_key_field_no_crash(self):
        step = _make_step(t_start=10.0, t_end=20.0)
        frames = [{"idx": 0, "t": 12.0}]  # no 'key'
        result = attach_missing_click_evidence(_make_guide([step]), frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"

    # 15. Empty frames list → no crash, source set to "none"
    def test_empty_frames_list_no_crash(self):
        step = _make_step(t_start=10.0, t_end=20.0)
        result = attach_missing_click_evidence(_make_guide([step]), [], max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"

    # 16. CLICK step with no timestamps and no frames → no crash, source stays None
    def test_click_step_no_timestamps_no_frames(self):
        step = _make_step(verb="CLICK")  # no t_start, no t_end
        result = attach_missing_click_evidence(_make_guide([step]), [], max_nearest_sec=3.0)
        # choose_nearest_frame_for_step returns None immediately (no timestamps)
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source == "none"


# ---------------------------------------------------------------------------
# Pipeline stage integration (lightweight, no real DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage_assigns_evidence_to_click_step():
    """Stage reads extract_frames from pipeline_artifacts and enriches guide_content."""
    from app.pipeline.stages.attach_evidence import run as attach_evidence_run

    sid = str(uuid.uuid4())
    frame_key = f"sessions/{sid}/frames/frame_0001.jpg"

    # Minimal guide_content with one CLICK step that has no frame evidence
    guide_content = {
        "schema_version": "1.0",
        "title": "T",
        "summary": "S",
        "steps": [
            {
                "id": "step-1",
                "order": 1,
                "title": "Inspect Container",
                "description": "Click the container.",
                "actions": [{"verb": "CLICK", "target": "Container", "value": None}],
                "evidence": {
                    "frame_keys": [],
                    "transcript_excerpt": "cliccando sul container",
                    "t_start": 36.0,
                    "t_end": 47.0,
                },
                "warnings": [],
                "notes": [],
                "confidence": 0.6,
            }
        ],
        "warnings": [],
        "notes": [],
    }

    # Fake session with pipeline_artifacts containing extract_frames
    session = MagicMock()
    session.id = sid
    session.guide_content = guide_content
    session.pipeline_artifacts = {
        "extract_frames": [
            {"idx": 0, "t": 34.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 37.0, "key": frame_key},
            {"idx": 2, "t": 41.0, "key": f"sessions/{sid}/frames/frame_0002.jpg"},
        ],
        # attach_evidence not yet done
    }

    db = AsyncMock()
    db.flush = AsyncMock()

    # Stub common.stage_done + common.record_stage so stage runs cleanly
    import app.pipeline.common as common_mod
    import app.pipeline.stages.attach_evidence as ae_mod

    original_stage_done = common_mod.stage_done
    original_record_stage = common_mod.record_stage

    common_mod.stage_done = lambda s, name: False
    common_mod.record_stage = AsyncMock()

    try:
        await attach_evidence_run(db, session)
    finally:
        common_mod.stage_done = original_stage_done
        common_mod.record_stage = original_record_stage

    # guide_content on the session was updated
    updated = session.guide_content
    assert isinstance(updated, dict)
    step_ev = updated["steps"][0]["evidence"]
    assert frame_key in step_ev["frame_keys"]
    assert step_ev["frame_source"] == "nearest_frame"
    assert step_ev["frame_distance_sec"] == 1.0  # |37 - 36| = 1.0


# ---------------------------------------------------------------------------
# Opacified key resolution (non-CLICK steps) & guide_has_opacified_keys
# ---------------------------------------------------------------------------

class TestOpacifiedKeyResolution:

    def test_non_click_step_opacified_key_resolved(self):
        """An OPEN step whose frame_key is an opacified stem must get it resolved
        to the full storage path — this is the bug that caused broken screenshots."""
        sid = "abc-session"
        full_key = f"sessions/{sid}/frames/frame_0002.jpg"
        step = _make_step(verb="OPEN", frame_keys=["frame_0002"])
        guide = _make_guide([step])
        frames = [
            {"idx": 0, "t": 2.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
            {"idx": 1, "t": 5.0, "key": full_key},
        ]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        assert result.steps[0].evidence.frame_keys == [full_key]
        assert result.steps[0].evidence.frame_source == "llm"

    def test_non_click_step_unresolvable_key_cleared(self):
        """A non-CLICK step with a hallucinated / unresolvable key gets cleared."""
        sid = "abc"
        step = _make_step(verb="VERIFY", frame_keys=["frame_FAKE"])
        guide = _make_guide([step])
        frames = [{"idx": 0, "t": 1.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"}]
        result = attach_missing_click_evidence(guide, frames, max_nearest_sec=3.0)
        # "frame_FAKE" has no matching stem → cleared
        assert result.steps[0].evidence.frame_keys == []
        assert result.steps[0].evidence.frame_source is None

    def test_guide_has_opacified_keys_detects_stem(self):
        sid = "abc"
        step = _make_step(verb="OPEN", frame_keys=["frame_0002"])
        guide = _make_guide([step])
        available = {f"sessions/{sid}/frames/frame_0002.jpg"}
        assert guide_has_opacified_keys(guide, available) is True

    def test_guide_has_opacified_keys_false_for_full_paths(self):
        sid = "abc"
        full_key = f"sessions/{sid}/frames/frame_0002.jpg"
        step = _make_step(verb="OPEN", frame_keys=[full_key])
        guide = _make_guide([step])
        available = {full_key}
        assert guide_has_opacified_keys(guide, available) is False

    def test_guide_has_opacified_keys_false_for_empty(self):
        step = _make_step(verb="OPEN")  # no frame_keys
        guide = _make_guide([step])
        assert guide_has_opacified_keys(guide, set()) is False


# ---------------------------------------------------------------------------
# PR4a: backward-compatible extract_frames format (list vs dict)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_accepts_extract_frames_as_dict():
    """attach_evidence works when extract_frames is stored as {frames: [...]}."""
    from app.pipeline.stages.attach_evidence import run as attach_evidence_run

    sid = str(uuid.uuid4())
    frame_key = f"sessions/{sid}/frames/frame_0001.jpg"

    guide_content = {
        "schema_version": "1.0",
        "title": "T",
        "summary": "S",
        "steps": [
            {
                "id": "step-1",
                "order": 1,
                "title": "T",
                "description": "D",
                "actions": [{"verb": "CLICK", "target": "Btn", "value": None}],
                "evidence": {
                    "frame_keys": [],
                    "transcript_excerpt": "",
                    "t_start": 36.0,
                    "t_end": 47.0,
                },
                "warnings": [],
                "notes": [],
                "confidence": 0.6,
            }
        ],
        "warnings": [],
        "notes": [],
    }

    session = MagicMock()
    session.id = sid
    session.guide_content = guide_content
    session.pipeline_artifacts = {
        "extract_frames": {
            "frames": [
                {"idx": 0, "t": 34.0, "key": f"sessions/{sid}/frames/frame_0000.jpg"},
                {"idx": 1, "t": 37.0, "key": frame_key},
            ]
        }
    }

    db = AsyncMock()
    db.flush = AsyncMock()

    import app.pipeline.common as common_mod

    original_stage_done = common_mod.stage_done
    original_record_stage = common_mod.record_stage

    common_mod.stage_done = lambda s, name: False
    common_mod.record_stage = AsyncMock()

    try:
        await attach_evidence_run(db, session)
    finally:
        common_mod.stage_done = original_stage_done
        common_mod.record_stage = original_record_stage

    updated = session.guide_content
    step_ev = updated["steps"][0]["evidence"]
    assert frame_key in step_ev["frame_keys"]
    assert step_ev["frame_source"] == "nearest_frame"
