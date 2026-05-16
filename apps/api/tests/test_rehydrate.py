"""Phase E: rehydrator."""
from __future__ import annotations

from app.sanitize import rehydrate_obj, rehydrate_text


def test_rehydrate_text_basic():
    out, stats = rehydrate_text("send to [EMAIL_1] now", {"[EMAIL_1]": "a@x.it"})
    assert out == "send to a@x.it now"
    assert stats.resolved == 1
    assert stats.unresolved == 0


def test_rehydrate_obj_walks_nested():
    obj = {
        "title": "Reset password for [EMAIL_1]",
        "steps": [
            {"text": "Open [URL_1]", "code": None},
            {"text": "Login with [EMAIL_1]"},
        ],
    }
    rmap = {"[EMAIL_1]": "user@x.it", "[URL_1]": "https://portal.x.it"}
    out, stats = rehydrate_obj(obj, rmap)
    assert out["title"] == "Reset password for user@x.it"
    assert out["steps"][0]["text"] == "Open https://portal.x.it"
    assert out["steps"][1]["text"] == "Login with user@x.it"
    # Three substitutions across the tree.
    assert stats.resolved == 3
    assert stats.unresolved == 0


def test_rehydrate_obj_records_unresolved():
    obj = {"x": "ghost [EMAIL_42] here"}
    out, stats = rehydrate_obj(obj, {})
    assert out == {"x": "ghost [EMAIL_42] here"}
    assert stats.unresolved == 1
    assert "[EMAIL_42]" in stats.unresolved_placeholders


def test_rehydrate_obj_preserves_non_strings():
    obj = {"n": 42, "b": True, "list": [1, 2, "[EMAIL_1]"]}
    out, _ = rehydrate_obj(obj, {"[EMAIL_1]": "a@x.it"})
    assert out == {"n": 42, "b": True, "list": [1, 2, "a@x.it"]}
