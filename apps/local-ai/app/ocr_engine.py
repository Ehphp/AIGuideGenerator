"""Local OCR engine module — Phase D.

Provides a single entry point :func:`ocr_frames` that, given a list of
already-resolved frame paths and their original storage keys, returns a
list of normalized OCR result dicts shaped exactly like
``schemas.OCRFrameResult`` (so the endpoint can `OCRFrameResult(**r)`
without further translation).

Engine dispatch:
- ``settings.ocr_engine == "stub"``      → return empty results, no native call.
- ``settings.ocr_engine == "tesseract"`` → use :mod:`pytesseract`. Requires
  the ``tesseract-ocr`` apt package + relevant ``tesseract-ocr-<lang>`` data.
- ``settings.ocr_engine == "paddle"``    → reserved; raises NotImplementedError.

Design constraints (privacy):
- Never logs OCR text content.
- Never returns filesystem paths back to the caller; only the original
  ``frame_key`` is echoed.
- Never lets a Tesseract import error crash the service when stub mode
  is selected — the import is lazy.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings

log = logging.getLogger("local-ai.ocr")


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def ocr_frames(
    frame_paths: list[Path],
    frame_keys: list[str],
    language: str | None,
) -> list[dict[str, Any]]:
    """Run OCR on the supplied frames.

    Returns one dict per input frame, in the same order. Each dict matches
    the :class:`app.schemas.OCRFrameResult` shape.
    """
    if len(frame_paths) != len(frame_keys):
        # Internal contract violation — should never happen via the endpoint.
        raise ValueError("frame_paths / frame_keys length mismatch")

    engine = (settings.ocr_engine or "stub").lower()
    lang = (language or settings.ocr_language or settings.ocr_lang or "eng").strip()

    if engine == "stub":
        return [_stub_result(key, lang) for key in frame_keys]

    if engine == "tesseract":
        return [
            _tesseract_one(path, key, lang) for path, key in zip(frame_paths, frame_keys, strict=True)
        ]

    if engine == "paddle":
        raise NotImplementedError("paddle OCR engine is not implemented yet")

    raise ValueError(f"unknown OCR engine: {engine!r}")


# ---------------------------------------------------------------------------
# Stub engine
# ---------------------------------------------------------------------------


def _stub_result(frame_key: str, language: str) -> dict[str, Any]:
    return {
        "frame_key": frame_key,
        "engine": "stub",
        "model": "stub",
        "language": language,
        "text": "",
        "blocks": [],
    }


# ---------------------------------------------------------------------------
# Tesseract engine
# ---------------------------------------------------------------------------


def _tesseract_one(path: Path, frame_key: str, language: str) -> dict[str, Any]:
    """Run Tesseract on a single frame; return a normalized result dict."""
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "pytesseract / Pillow are not installed. Install the 'ocr' extra "
            "(pip install -e .[ocr]) or run with OCR_ENGINE=stub."
        ) from exc

    try:
        with Image.open(path) as img:
            img.load()
            processed = _preprocess_for_ocr(img) if settings.ocr_preprocess else img
            data = pytesseract.image_to_data(
                processed,
                lang=language,
                output_type=pytesseract.Output.DICT,
            )
    except pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        raise RuntimeError(
            "tesseract binary not found in PATH. Install the 'tesseract-ocr' "
            "package or run with OCR_ENGINE=stub."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Surface a generic message; never include text content or path.
        log.warning("tesseract failed on a frame: %s", type(exc).__name__)
        return {
            "frame_key": frame_key,
            "engine": "tesseract",
            "model": "tesseract",
            "language": language,
            "text": "",
            "blocks": [],
        }

    blocks = _normalize_tesseract_blocks(data)
    full_text = " ".join(b["text"] for b in blocks).strip()

    return {
        "frame_key": frame_key,
        "engine": "tesseract",
        "model": "tesseract",
        "language": language,
        "text": full_text,
        "blocks": blocks,
    }


def _preprocess_for_ocr(img):
    """Apply screen-capture-friendly preprocessing for Tesseract.

    Converts to grayscale, upscales 2x with Lanczos resampling, and applies
    a light contrast stretch. These transformations are well-known to
    improve Tesseract accuracy on UI screenshots (small text, anti-aliased
    edges) without slowing inference materially.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore[import-not-found]
    except ImportError:
        return img
    g = img.convert("L")
    g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)
    return g


def _normalize_tesseract_blocks(data: dict[str, list]) -> list[dict[str, Any]]:
    """Convert the tesseract `image_to_data` dict into normalized blocks.

    - Drops empty / whitespace-only text entries.
    - Drops entries with conf < 0 (Tesseract's "no info" marker).
    - Drops entries below ``settings.ocr_min_confidence`` (normalized 0..1).
    - bbox is ``{x, y, w, h}`` in pixels.
    """
    out: list[dict[str, Any]] = []
    n = len(data.get("text") or [])
    min_conf = max(0.0, float(settings.ocr_min_confidence or 0.0))

    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            raw_conf = float(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if raw_conf < 0:
            continue
        norm_conf = raw_conf / 100.0  # tesseract conf is 0..100
        if norm_conf < min_conf:
            continue
        try:
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
        except (KeyError, ValueError, TypeError):
            continue
        # Bounding boxes were computed on the 2x-upscaled image; rescale
        # back to original pixel coordinates so downstream stages
        # (extract_visual_facts) interpret them correctly.
        if settings.ocr_preprocess:
            x //= 2; y //= 2; w //= 2; h //= 2
        out.append(
            {
                "text": text,
                "confidence": round(norm_conf, 4),
                "bbox": {"x": x, "y": y, "w": w, "h": h},
            }
        )
    return out
