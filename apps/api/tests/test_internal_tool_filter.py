"""Unit tests for app.pipeline.internal_tool_filter."""
from __future__ import annotations

import pytest

from app.pipeline.internal_tool_filter import (
    filter_internal_tool_noise_from_timeline,
    is_internal_tool_event,
    trim_internal_tool_prefix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _transcript(text: str, t: float = 0.0) -> dict:
    return {"kind": "transcript", "t": t, "t_end": t + 1.0, "text": text}


def _frame(ocr: str, t: float = 0.0) -> dict:
    return {
        "kind": "frame",
        "t": t,
        "frame_key": f"sessions/test/frames/frame_{int(t):04d}.jpg",
        "ocr_text": ocr,
        "ui_summary": f"UI text: {ocr[:40]}",
    }


# ---------------------------------------------------------------------------
# is_internal_tool_event
# ---------------------------------------------------------------------------

class TestIsInternalToolEvent:
    def test_strong_term_guide_generator(self):
        assert is_internal_tool_event(_transcript("Guide Generator ready")) is True

    def test_strong_term_download_docx(self):
        assert is_internal_tool_event(_frame("Download DOCX button visible")) is True

    def test_strong_term_edit_guide(self):
        assert is_internal_tool_event(_transcript("Edit guide panel opened")) is True

    def test_strong_term_generate_guide(self):
        assert is_internal_tool_event(_frame("Generate guide button")) is True

    def test_strong_term_upload_video(self):
        assert is_internal_tool_event(_transcript("Upload video to start")) is True

    def test_strong_term_start_recording(self):
        assert is_internal_tool_event(_transcript("Start recording now")) is True

    def test_strong_term_stop_recording(self):
        assert is_internal_tool_event(_transcript("Stop recording")) is True

    def test_strong_term_reprocess(self):
        assert is_internal_tool_event(_frame("Reprocess session")) is True

    def test_strong_term_case_insensitive(self):
        assert is_internal_tool_event(_transcript("guide generator status")) is True

    def test_real_docker_event_not_noise(self):
        assert is_internal_tool_event(_transcript("Docker Desktop Containers")) is False

    def test_real_click_event_not_noise(self):
        assert is_internal_tool_event(_transcript("Click container name")) is False

    def test_empty_event_not_noise(self):
        assert is_internal_tool_event({"kind": "transcript", "t": 0.0}) is False

    # Generic words that must NOT classify an event as noise on their own.
    def test_generic_word_ready_alone_not_noise(self):
        assert is_internal_tool_event(_transcript("Container is ready")) is False

    def test_generic_word_processing_alone_not_noise(self):
        assert is_internal_tool_event(_transcript("processing the image")) is False

    def test_generic_word_session_alone_not_noise(self):
        assert is_internal_tool_event(_transcript("session timeout")) is False

    def test_generic_word_ready_alongside_strong_term_is_noise(self):
        # The strong term "Guide Generator" is what triggers noise; "ready" is irrelevant.
        assert is_internal_tool_event(_transcript("Guide Generator ready")) is True

    def test_ocr_text_field_checked(self):
        event = {"kind": "frame", "t": 0.0, "ocr_text": "Download DOCX", "ui_summary": ""}
        assert is_internal_tool_event(event) is True

    def test_ui_summary_field_checked(self):
        event = {"kind": "frame", "t": 0.0, "ocr_text": "", "ui_summary": "Edit guide button"}
        assert is_internal_tool_event(event) is True


# ---------------------------------------------------------------------------
# trim_internal_tool_prefix
# ---------------------------------------------------------------------------

class TestTrimInternalToolPrefix:
    def test_all_noise_prefix_removed(self):
        events = [
            _transcript("Guide Generator ready Download DOCX Edit guide", t=0.0),
            _transcript("Docker Desktop Containers", t=1.0),
            _transcript("Click container name", t=2.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert len(kept) == 2
        assert len(dropped) == 1
        assert kept[0]["text"] == "Docker Desktop Containers"

    def test_multiple_noise_events_in_prefix_all_removed(self):
        events = [
            _frame("Guide Generator", t=0.0),
            _frame("Download DOCX Edit guide Generate guide", t=1.0),
            _transcript("Open terminal", t=2.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert len(dropped) == 2
        assert len(kept) == 1

    def test_noise_in_middle_not_removed(self):
        """Noise events after the first real event must be left in place."""
        events = [
            _transcript("Open terminal", t=0.0),
            _frame("Guide Generator", t=1.0),    # noise but NOT in prefix
            _transcript("Run docker ps", t=2.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert len(dropped) == 0
        assert len(kept) == 3

    def test_no_noise_at_all(self):
        events = [
            _transcript("Open terminal", t=0.0),
            _transcript("Run docker ps", t=1.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert dropped == []
        assert kept == events

    def test_all_noise_returns_empty_kept(self):
        events = [
            _frame("Guide Generator ready", t=0.0),
            _frame("Download DOCX", t=1.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert kept == []
        assert len(dropped) == 2

    def test_empty_input(self):
        kept, dropped = trim_internal_tool_prefix([])
        assert kept == []
        assert dropped == []

    def test_weak_term_only_in_prefix_not_removed(self):
        """A prefix event containing only a generic word must NOT be trimmed."""
        events = [
            _transcript("Container is ready", t=0.0),
            _transcript("Open terminal", t=1.0),
        ]
        kept, dropped = trim_internal_tool_prefix(events)
        assert dropped == []
        assert len(kept) == 2


# ---------------------------------------------------------------------------
# filter_internal_tool_noise_from_timeline
# ---------------------------------------------------------------------------

class TestFilterInternalToolNoiseFromTimeline:
    def test_metadata_key_always_present(self):
        result = filter_internal_tool_noise_from_timeline({"events": []})
        assert "internal_tool_filter" in result
        assert result["internal_tool_filter"]["dropped_prefix_events"] == 0

    def test_original_timeline_not_mutated(self):
        events = [_transcript("Guide Generator", t=0.0), _transcript("Run docker ps", t=1.0)]
        original = {"language": "en", "events": events}
        filter_internal_tool_noise_from_timeline(original)
        assert len(original["events"]) == 2  # untouched

    def test_dropped_prefix_count_correct(self):
        timeline = {
            "language": "en",
            "events": [
                _transcript("Guide Generator ready Download DOCX Edit guide", t=0.0),
                _transcript("Docker Desktop Containers", t=1.0),
                _transcript("Click container name", t=2.0),
            ],
        }
        result = filter_internal_tool_noise_from_timeline(timeline)
        assert result["internal_tool_filter"]["dropped_prefix_events"] == 1
        assert len(result["events"]) == 2

    def test_language_and_other_fields_preserved(self):
        timeline = {
            "language": "it",
            "source": "test",
            "events": [_transcript("Open terminal", t=0.0)],
        }
        result = filter_internal_tool_noise_from_timeline(timeline)
        assert result["language"] == "it"
        assert result["source"] == "test"

    def test_zero_dropped_when_no_noise(self):
        timeline = {
            "events": [
                _transcript("Open terminal", t=0.0),
                _transcript("Run docker ps", t=1.0),
            ]
        }
        result = filter_internal_tool_noise_from_timeline(timeline)
        assert result["internal_tool_filter"]["dropped_prefix_events"] == 0
        assert len(result["events"]) == 2

    def test_missing_events_key(self):
        result = filter_internal_tool_noise_from_timeline({"language": "en"})
        assert result["internal_tool_filter"]["dropped_prefix_events"] == 0
        assert result["events"] == []
