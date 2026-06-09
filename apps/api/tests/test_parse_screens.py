"""Unit tests for app.pipeline.stages.parse_screens (pure helpers)."""
from __future__ import annotations

from app.pipeline.stages.parse_screens import (
    build_summary,
    collect_uncertainties,
    compute_ui_hints,
    derive_frame,
    select_important_text,
)


# ---------------------------------------------------------------------------
# compute_ui_hints
# ---------------------------------------------------------------------------


class TestComputeUIHints:
    def test_empty_text_no_elements(self):
        h = compute_ui_hints("", [])
        assert h == {
            "has_terminal": False,
            "has_code": False,
            "has_browser": False,
            "has_form": False,
            "has_buttons": False,
            "has_error_message": False,
            "has_success_message": False,
        }

    def test_terminal_git_command(self):
        h = compute_ui_hints("$ git commit -m 'fix'", [])
        assert h["has_terminal"] is True

    def test_terminal_powershell_prompt(self):
        h = compute_ui_hints("PS C:\\Users\\foo> docker ps", [])
        assert h["has_terminal"] is True

    def test_code_python_def(self):
        h = compute_ui_hints("def foo(): return 42", [])
        assert h["has_code"] is True

    def test_browser_url(self):
        h = compute_ui_hints("https://github.com/foo/bar", [])
        assert h["has_browser"] is True

    def test_buttons_from_elements(self):
        els = [{"type": "button", "label": "Save"}]
        h = compute_ui_hints("Save", els)
        assert h["has_buttons"] is True

    def test_form_requires_button_and_label_word(self):
        els = [{"type": "button", "label": "Create"}]
        h = compute_ui_hints("Repository name", els)
        assert h["has_form"] is True

    def test_form_false_without_button(self):
        h = compute_ui_hints("Repository name", [])
        assert h["has_form"] is False

    def test_error_from_text(self):
        h = compute_ui_hints("Error: invalid token", [])
        assert h["has_error_message"] is True

    def test_error_from_element_type(self):
        els = [{"type": "error_message", "label": "boom"}]
        h = compute_ui_hints("", els)
        assert h["has_error_message"] is True

    def test_success_message(self):
        h = compute_ui_hints("Repository created successfully", [])
        assert h["has_success_message"] is True


# ---------------------------------------------------------------------------
# select_important_text
# ---------------------------------------------------------------------------


class TestSelectImportantText:
    def test_empty(self):
        assert select_important_text([]) == []

    def test_orders_by_type_priority(self):
        els = [
            {"type": "list_item", "label": "repo-a", "confidence": 0.9},
            {"type": "title", "label": "Create a new repository", "confidence": 0.7},
            {"type": "button", "label": "Create repository", "confidence": 0.8},
        ]
        out = select_important_text(els)
        assert out[0] == "Create a new repository"  # title first
        assert out[1] == "Create repository"        # button second
        assert "repo-a" in out

    def test_dedup_case_insensitive(self):
        els = [
            {"type": "button", "label": "Save", "confidence": 0.9},
            {"type": "button", "label": "save", "confidence": 0.5},
        ]
        out = select_important_text(els)
        assert out == ["Save"]

    def test_max_items(self):
        els = [
            {"type": "list_item", "label": f"item-{i}", "confidence": 0.8}
            for i in range(20)
        ]
        out = select_important_text(els, max_items=5)
        assert len(out) == 5

    def test_filters_unknown_types(self):
        els = [
            {"type": "text", "label": "noise", "confidence": 0.9},
            {"type": "button", "label": "Submit", "confidence": 0.8},
        ]
        assert select_important_text(els) == ["Submit"]


# ---------------------------------------------------------------------------
# collect_uncertainties
# ---------------------------------------------------------------------------


class TestCollectUncertainties:
    def test_low_yield_and_no_signal(self):
        vf = {
            "informativeness_score": 0.05,
            "screen_title": None,
            "diagnostics": {"uncertain": False, "n_blocks_kept": 2},
        }
        hints = {k: False for k in (
            "has_terminal", "has_code", "has_browser",
            "has_form", "has_buttons", "has_error_message",
            "has_success_message",
        )}
        flags = collect_uncertainties(vf, hints, important_text=[])
        assert "low_ocr_yield" in flags
        assert "no_screen_title" in flags
        assert "no_important_text" in flags
        assert "no_ui_signal" in flags

    def test_no_blocks_kept(self):
        vf = {
            "informativeness_score": 0.0,
            "screen_title": "X",
            "diagnostics": {"uncertain": False, "n_blocks_kept": 0},
        }
        hints = {"has_buttons": True}
        flags = collect_uncertainties(vf, hints, important_text=["X"])
        assert "no_blocks_kept" in flags

    def test_clean_frame_has_no_flags(self):
        vf = {
            "informativeness_score": 0.7,
            "screen_title": "Create a new repository",
            "diagnostics": {"uncertain": False, "n_blocks_kept": 12},
        }
        hints = {"has_buttons": True, "has_form": True}
        flags = collect_uncertainties(vf, hints, important_text=["Create"])
        assert flags == []

    def test_region_filter_uncertain_flag(self):
        vf = {
            "informativeness_score": 0.6,
            "screen_title": "Title",
            "diagnostics": {"uncertain": True, "n_blocks_kept": 5},
        }
        hints = {"has_buttons": True}
        flags = collect_uncertainties(vf, hints, important_text=["x"])
        assert "region_filter_too_aggressive" in flags


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_no_signal(self):
        assert build_summary(None, None, None, []) == "no signal"

    def test_full_summary(self):
        s = build_summary(
            "form_page", "Create repo", "github_web", ["Repository name", "Create"]
        )
        assert "form_page" in s
        assert "github_web" in s
        assert "Create repo" in s
        assert "Repository name" in s


# ---------------------------------------------------------------------------
# derive_frame (integration of helpers)
# ---------------------------------------------------------------------------


class TestDeriveFrame:
    def test_github_form_page(self):
        analyze_entry = {
            "idx": 7,
            "t": 12.34,
            "key": "sessions/x/frames/frame_0007.jpg",
            "ocr_text": "Repository name Private Create repository",
        }
        vf = {
            "frame_key": "sessions/x/frames/frame_0007.jpg",
            "main_content_text": "Repository name Private Create repository",
            "app_context": "github_web",
            "screen_title": "Create a new repository",
            "informativeness_score": 0.6,
            "visible_ui_elements": [
                {"type": "title", "label": "Create a new repository", "confidence": 0.8},
                {"type": "button", "label": "Create repository", "confidence": 0.9},
            ],
            "diagnostics": {"uncertain": False, "n_blocks_kept": 5},
        }
        out = derive_frame(analyze_entry, vf)
        assert out["t"] == 12.34
        assert out["frame_key"].endswith("frame_0007.jpg")
        assert out["app_hint"] == "github_web"
        assert out["screen_title"] == "Create a new repository"
        assert out["screen_type"] == "form_page"
        assert out["ui_hints"]["has_form"] is True
        assert out["ui_hints"]["has_buttons"] is True
        assert "Create a new repository" in out["important_text"]
        assert out["confidence"] == 0.6
        assert "no signal" not in out["summary"]

    def test_terminal_screen(self):
        analyze_entry = {
            "idx": 1,
            "t": 5.0,
            "key": "sessions/x/frames/frame_0001.jpg",
            "ocr_text": "$ git push origin main",
        }
        out = derive_frame(analyze_entry, None)
        assert out["screen_type"] == "terminal"
        assert out["ui_hints"]["has_terminal"] is True
        # No visual_facts → low confidence + flags
        assert out["confidence"] == 0.0
        assert "low_ocr_yield" in out["uncertainties"]

    def test_error_takes_priority_over_form(self):
        analyze_entry = {
            "idx": 3,
            "t": 9.0,
            "key": "sessions/x/frames/frame_0003.jpg",
            "ocr_text": "Error: name already exists",
        }
        vf = {
            "main_content_text": "Error: name already exists",
            "informativeness_score": 0.4,
            "visible_ui_elements": [
                {"type": "button", "label": "Retry", "confidence": 0.7},
            ],
            "diagnostics": {"uncertain": False, "n_blocks_kept": 3},
        }
        out = derive_frame(analyze_entry, vf)
        assert out["screen_type"] == "error_screen"
        assert out["ui_hints"]["has_error_message"] is True

    def test_long_ocr_text_truncated(self):
        long_text = "abc " * 500
        analyze_entry = {
            "idx": 0, "t": 0.0,
            "key": "k.jpg", "ocr_text": long_text,
        }
        out = derive_frame(analyze_entry, None)
        assert len(out["ocr_text"]) <= 600
        assert out["ocr_text"].endswith("…")
