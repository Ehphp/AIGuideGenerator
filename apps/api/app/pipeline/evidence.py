"""Deterministic evidence-attachment helpers (Phase F).

Pure, stateless functions — no LLM calls, no I/O, no image loading.
The stage wrapper (stages/attach_evidence.py) feeds the real artifacts;
unit tests call these functions directly with in-memory data.

Rule implemented
----------------
For every Step that contains at least one CLICK action and whose
``evidence.frame_keys`` is empty or contains only keys that are not in the
set produced by ``extract_frames``:

1. If the step has both ``t_start`` and ``t_end``:
   a. Collect frames inside [t_start, t_end].
   b. If any, return the one closest to ``t_start``.
2. Prefer the first frame that comes *after* t_end (within max_nearest_sec × 5
   seconds).  For navigation / CLICK actions this post-action frame shows the
   destination state (e.g. the navigated-to page), which is more informative
   than the transient state captured just before the click.
3. Fallback: return the frame nearest to ``t_start`` (or ``t_end`` if
   ``t_start`` is absent), provided the distance ≤ ``max_nearest_sec``.
4. If no suitable frame is found, leave ``frame_keys`` empty and set
   ``frame_source = "none"``.

Additionally, if the LLM already assigned a frame that comes *before*
``t_start`` (a pre-action frame), the deterministic selector above is re-run
and its result overrides the LLM choice when a better post-action candidate
exists.

Steps that already have valid ``frame_keys`` pointing to a post-action frame
(``key_t >= t_start``) are left intact; only ``frame_source`` is backfilled
(to ``"llm"``) if it was previously unset.
"""
from __future__ import annotations

from app.schemas.guide import Evidence, Guide, Step


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def step_has_click(step: Step) -> bool:
    """Return True if the step contains at least one CLICK action."""
    return any(a.verb == "CLICK" for a in step.actions)


def valid_frame_keys(frame_keys: list[str], available_keys: set[str]) -> list[str]:
    """Return only the keys that exist in the known ``extract_frames`` set.

    Also resolves opacified stems produced by ``prepare_for_egress`` back to
    their full storage paths.  For example, GPT may write ``"frame_0007"``
    (the stem we sent it) which maps back to
    ``"sessions/<uuid>/frames/frame_0007.jpg"``.

    Resolution order:
    1. Exact match against ``available_keys``.
    2. Stem match: strip directory + extension from both sides and compare.
       The first matching full path wins.
    """
    if not frame_keys:
        return []
    # Build stem → full_key lookup once.
    stem_to_full: dict[str, str] = {}
    for k in available_keys:
        stem = k.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
        stem_to_full.setdefault(stem, k)

    result: list[str] = []
    for k in frame_keys:
        if k in available_keys:
            result.append(k)
        else:
            # Try stem resolution (handles opacified keys from egress).
            candidate_stem = k.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
            resolved = stem_to_full.get(candidate_stem)
            if resolved:
                result.append(resolved)
    return result


def choose_nearest_frame_for_step(
    step: Step,
    frames: list[dict],
    max_nearest_sec: float,
) -> dict | None:
    """Choose the best frame for a step that needs evidence.

    Parameters
    ----------
    step:
        The step whose ``evidence`` timestamps are used.
    frames:
        Full ``extract_frames`` list — each item is ``{idx, t, key}``.
    max_nearest_sec:
        Maximum allowed distance (seconds) for the nearest-frame fallback.

    Returns
    -------
    The chosen frame dict, or ``None`` if no suitable frame is available.
    """
    if not frames:
        return None

    t_start = step.evidence.t_start
    t_end = step.evidence.t_end

    # Determine the primary reference timestamp (rules 6, 7, 8).
    if t_start is not None:
        t_ref = t_start
    elif t_end is not None:
        t_ref = t_end
    else:
        return None  # Rule 8: no timestamps → do not assign

    # Rule 4: prefer frames strictly inside the step range.
    if t_start is not None and t_end is not None:
        in_range = [f for f in frames if t_start <= f["t"] <= t_end]
        if in_range:
            # Among in-range frames pick the one closest to t_start.
            return min(in_range, key=lambda f: abs(f["t"] - t_start))

    # Rule 4b: prefer the first frame that comes *after* t_end over frames
    # that precede t_start.  For CLICK / navigation actions the post-action
    # frame shows the destination state (e.g. the newly-loaded page), which
    # is more informative than whatever was on screen moments before the
    # click.  Search window: max_nearest_sec * _POST_CLICK_WINDOW_FACTOR.
    # Guard: only apply when t_start is known (otherwise there is no clear
    # "action direction" and the nearest-within-threshold rule is better).
    # Lowered from x5 to x2 to avoid attaching frames many seconds after the
    # action that may show a completely different UI state.
    _POST_CLICK_WINDOW_FACTOR = 2
    if t_start is not None and t_end is not None:
        just_after = [
            f for f in frames
            if t_end < f["t"] <= t_end + max_nearest_sec * _POST_CLICK_WINDOW_FACTOR
        ]
        if just_after:
            return min(just_after, key=lambda f: f["t"] - t_end)

    # Rule 5 / 6 / 7: nearest to t_ref within the configured window.
    nearest = min(frames, key=lambda f: abs(f["t"] - t_ref))
    if abs(nearest["t"] - t_ref) <= max_nearest_sec:
        return nearest

    return None


def guide_has_opacified_keys(guide: Guide, available_keys: set[str]) -> bool:
    """Return True if any step contains frame_keys that are unresolved stems.

    An "opacified" key is one produced by ``prepare_for_egress`` — it has no
    path separator and no file extension, e.g. ``"frame_0007"`` instead of
    ``"sessions/<uuid>/frames/frame_0007.jpg"``.
    """
    for step in guide.steps:
        for k in step.evidence.frame_keys:
            if k not in available_keys and "/" not in k:
                return True
    return False


def attach_missing_click_evidence(
    guide: Guide,
    frames: list[dict],
    max_nearest_sec: float = 3.0,
) -> Guide:
    """Ensure every CLICK-bearing step has at least one valid frame key.

    Also resolves opacified frame_keys (stems like ``"frame_0007"`` produced
    by ``prepare_for_egress``) back to full storage paths for **all** steps,
    not only CLICK steps.

    Modifies ``guide`` in place (Pydantic v2 models are mutable) and returns
    it for convenience. The function is **idempotent**: running it twice
    yields the same result.

    Parameters
    ----------
    guide:
        The validated ``Guide`` object produced by ``validate_guide``.
    frames:
        The ``extract_frames`` pipeline artifact — list of
        ``{idx: int, t: float, key: str}``.
    max_nearest_sec:
        Maximum allowed distance for the nearest-frame fallback (Rule 5).
    """
    # Pre-filter to frames that have both a valid timestamp and a valid key.
    # Defensive: extract_frames always produces well-formed entries, but guard
    # against corrupt artifacts or future schema changes.
    valid_frames: list[dict] = [
        f
        for f in frames
        if isinstance(f.get("t"), (int, float)) and isinstance(f.get("key"), str)
    ]
    available_keys: set[str] = {str(f["key"]) for f in valid_frames}

    for step in guide.steps:
        # First: resolve opacified keys for every step (CLICK or not).  This
        # handles stems like "frame_0002" that GPT copied verbatim from the
        # egress-sanitised timeline.
        resolved = valid_frame_keys(step.evidence.frame_keys, available_keys)
        if resolved != step.evidence.frame_keys:
            step.evidence.frame_keys = resolved
            if resolved and step.evidence.frame_source is None:
                step.evidence.frame_source = "llm"

        if not step_has_click(step):
            # Non-CLICK steps: key resolution above is all we do — do not
            # attempt nearest-frame assignment without an anchor action.
            continue

        existing_valid = valid_frame_keys(step.evidence.frame_keys, available_keys)

        if existing_valid:
            # Evidence is already usable; strip any hallucinated keys.
            # However: if the LLM chose a frame that comes *before* the step
            # starts, re-run the deterministic selector (which now prefers
            # post-action frames via Rule 4b) and override when it finds a
            # better candidate.  This handles the common case where the LLM
            # picks the last frame visible in the timeline before the action
            # rather than the frame that shows the result of the action.
            if step.evidence.t_start is not None:
                llm_ts = next(
                    (f["t"] for f in valid_frames if f["key"] == existing_valid[0]),
                    None,
                )
                if llm_ts is not None and llm_ts < step.evidence.t_start:
                    override = choose_nearest_frame_for_step(
                        step, valid_frames, max_nearest_sec
                    )
                    if override and override["key"] != existing_valid[0]:
                        t_ref = step.evidence.t_start
                        step.evidence.frame_keys = [override["key"]]
                        step.evidence.frame_source = "nearest_frame"
                        step.evidence.frame_distance_sec = round(
                            abs(override["t"] - t_ref), 3
                        )
                        continue

            step.evidence.frame_keys = existing_valid
            if step.evidence.frame_source is None:
                step.evidence.frame_source = "llm"
            continue

        # No valid evidence — attempt deterministic assignment.
        chosen = choose_nearest_frame_for_step(step, valid_frames, max_nearest_sec)
        if chosen:
            t_ref = (
                step.evidence.t_start
                if step.evidence.t_start is not None
                else step.evidence.t_end
            )
            step.evidence.frame_keys = [chosen["key"]]
            step.evidence.frame_source = "nearest_frame"
            step.evidence.frame_distance_sec = (
                round(abs(chosen["t"] - t_ref), 3) if t_ref is not None else None
            )
        else:
            # Record that we looked and found nothing. Also clear any invalid
            # keys that were left over from the LLM (e.g. hallucinated paths).
            step.evidence.frame_keys = []
            step.evidence.frame_source = "none"

    return guide
