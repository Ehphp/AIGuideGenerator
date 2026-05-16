from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.normalize_actions import normalize_guide_dict, normalize_verb
from app.pipeline.stages.validate_guide import _try_parse


def _build_guide_with_verbs(verbs: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "title": "Guide",
        "summary": "Summary",
        "estimated_duration_minutes": 1.0,
        "prerequisites": [],
        "tools_or_systems": [],
        "steps": [
            {
                "id": "step-1",
                "order": 1,
                "title": "Step",
                "description": "Do things",
                "actions": [
                    {"verb": verb, "target": f"target-{i}", "value": None}
                    for i, verb in enumerate(verbs, start=1)
                ],
                "evidence": {
                    "frame_keys": [],
                    "transcript_excerpt": "",
                    "t_start": 0.0,
                    "t_end": 1.0,
                },
                "warnings": [],
                "notes": [],
                "confidence": 0.8,
            }
        ],
        "warnings": [],
        "notes": [],
        "troubleshooting": [],
        "metadata": {
            "generated_by": "test",
            "generated_at": "",
            "source_session_id": "",
            "source_duration_sec": None,
        },
    }


def test_normalize_verb_maps_aliases_to_canonical() -> None:
    assert normalize_verb("Click") == "CLICK"
    assert normalize_verb("navigate to") == "NAVIGATE"
    assert normalize_verb("enter") == "TYPE"


def test_normalize_verb_falls_back_to_uppercase() -> None:
    assert normalize_verb("custom_action") == "CUSTOM_ACTION"


def test_normalize_guide_dict_updates_action_verbs() -> None:
    guide = _build_guide_with_verbs(["go to", "press", "custom_action"])

    normalized = normalize_guide_dict(guide)

    verbs = [a["verb"] for a in normalized["steps"][0]["actions"]]
    assert verbs == ["NAVIGATE", "CLICK", "CUSTOM_ACTION"]


def test_try_parse_applies_action_normalization() -> None:
    raw = json.dumps(_build_guide_with_verbs(["navigate to", "click", "download"]))

    guide, err = _try_parse(raw)

    assert err is None
    assert guide is not None
    verbs = [a.verb for a in guide.steps[0].actions]
    assert verbs == ["NAVIGATE", "CLICK", "DOWNLOAD"]


def test_prompt_contains_action_vocabulary_guidance() -> None:
    prompt_path = Path(__file__).resolve().parents[1] / "app" / "pipeline" / "prompts" / "guide_generation.md"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "Use this action vocabulary" in prompt
    assert "OPEN, NAVIGATE, CLICK, TYPE, SELECT, CONFIRM" in prompt
    assert "MUST include at least one" in prompt
