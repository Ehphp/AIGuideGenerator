"""Phase D: ocr_engine — stub vs tesseract dispatch + Tesseract normalization.

These tests never invoke the real `tesseract` binary. They monkeypatch
`pytesseract.image_to_data` so we can verify normalization without a native
dependency.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app import ocr_engine


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    # Default engine in tests is stub; tests that need tesseract opt in.
    monkeypatch.setattr("app.config.settings.ocr_engine", "stub")
    monkeypatch.setattr("app.config.settings.ocr_language", "eng+ita")
    monkeypatch.setattr("app.config.settings.ocr_lang", "eng+ita")
    monkeypatch.setattr("app.config.settings.ocr_min_confidence", 0.0)
    yield


# ---------------------------------------------------------------------------
# Stub engine
# ---------------------------------------------------------------------------


def test_stub_returns_one_per_key():
    keys = ["sessions/aaa/frames/frame_0001.jpg", "sessions/aaa/frames/frame_0002.jpg"]
    paths = [Path("/tmp/a.jpg"), Path("/tmp/b.jpg")]
    out = ocr_engine.ocr_frames(paths, keys, language="it")
    assert len(out) == 2
    for r, k in zip(out, keys, strict=True):
        assert r["frame_key"] == k
        assert r["engine"] == "stub"
        assert r["model"] == "stub"
        assert r["text"] == ""
        assert r["blocks"] == []


def test_unknown_engine_raises(monkeypatch):
    monkeypatch.setattr("app.config.settings.ocr_engine", "magic")
    with pytest.raises(ValueError, match="unknown OCR engine"):
        ocr_engine.ocr_frames([Path("x")], ["sessions/a/frames/x.jpg"], language=None)


def test_paddle_engine_not_implemented(monkeypatch):
    monkeypatch.setattr("app.config.settings.ocr_engine", "paddle")
    with pytest.raises(NotImplementedError):
        ocr_engine.ocr_frames([Path("x")], ["sessions/a/frames/x.jpg"], language=None)


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        ocr_engine.ocr_frames([Path("a")], ["k1", "k2"], language=None)


# ---------------------------------------------------------------------------
# Tesseract block normalization
# ---------------------------------------------------------------------------


def test_normalize_drops_empty_text_and_negative_conf():
    raw = {
        "text":   ["",     "hello",   "  ",  "world"],
        "conf":   ["95",   "92",      "80",  "-1"],
        "left":   [0,      10,        20,    30],
        "top":    [0,      11,        22,    33],
        "width":  [100,    50,        50,    50],
        "height": [20,     20,        20,    20],
    }
    blocks = ocr_engine._normalize_tesseract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "hello"
    assert blocks[0]["confidence"] == pytest.approx(0.92)
    assert blocks[0]["bbox"] == {"x": 10, "y": 11, "w": 50, "h": 20}


def test_normalize_respects_min_confidence(monkeypatch):
    monkeypatch.setattr("app.config.settings.ocr_min_confidence", 0.7)
    raw = {
        "text":   ["lo",   "hi"],
        "conf":   ["50",   "85"],
        "left":   [0,      10],
        "top":    [0,      0],
        "width":  [10,     10],
        "height": [10,     10],
    }
    blocks = ocr_engine._normalize_tesseract_blocks(raw)
    assert [b["text"] for b in blocks] == ["hi"]


def test_normalize_handles_garbage_conf_gracefully():
    raw = {
        "text":   ["x"],
        "conf":   ["not-a-number"],
        "left":   [0], "top": [0], "width": [1], "height": [1],
    }
    assert ocr_engine._normalize_tesseract_blocks(raw) == []


# ---------------------------------------------------------------------------
# Tesseract dispatch (with mocked pytesseract module)
# ---------------------------------------------------------------------------


def _install_fake_pytesseract(monkeypatch, image_to_data=None, raise_not_found=False):
    """Plant a fake `pytesseract` and `PIL.Image` in sys.modules."""
    fake_pyt = types.ModuleType("pytesseract")
    class _Output:
        DICT = "dict"
    fake_pyt.Output = _Output
    class _TesseractNotFoundError(Exception):
        pass
    fake_pyt.TesseractNotFoundError = _TesseractNotFoundError
    if raise_not_found:
        def _raise(*a, **kw):
            raise _TesseractNotFoundError("no tesseract")
        fake_pyt.image_to_data = _raise
    else:
        fake_pyt.image_to_data = image_to_data or (lambda *a, **kw: {
            "text": ["hello"], "conf": ["90"],
            "left": [1], "top": [2], "width": [3], "height": [4],
        })
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pyt)

    fake_pil = types.ModuleType("PIL")
    fake_pil_image = types.ModuleType("PIL.Image")
    class _FakeImg:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def load(self): return None
    fake_pil_image.open = lambda p: _FakeImg()
    fake_pil.Image = fake_pil_image
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_pil_image)
    return fake_pyt


def test_tesseract_dispatch_normalizes_results(monkeypatch):
    _install_fake_pytesseract(monkeypatch)
    monkeypatch.setattr("app.config.settings.ocr_engine", "tesseract")

    out = ocr_engine.ocr_frames(
        [Path("/tmp/a.jpg")],
        ["sessions/a/frames/frame_0001.jpg"],
        language="ita",
    )
    assert len(out) == 1
    r = out[0]
    assert r["engine"] == "tesseract"
    assert r["model"] == "tesseract"
    assert r["language"] == "ita"
    assert r["text"] == "hello"
    assert len(r["blocks"]) == 1
    assert r["blocks"][0]["text"] == "hello"
    assert r["blocks"][0]["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}


def test_tesseract_missing_binary_raises_runtime_error(monkeypatch):
    _install_fake_pytesseract(monkeypatch, raise_not_found=True)
    monkeypatch.setattr("app.config.settings.ocr_engine", "tesseract")
    with pytest.raises(RuntimeError, match="tesseract binary not found"):
        ocr_engine.ocr_frames(
            [Path("/tmp/a.jpg")], ["sessions/a/frames/frame_0001.jpg"], language=None
        )


def test_tesseract_per_frame_failure_returns_empty_block(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("decoder choked")
    _install_fake_pytesseract(monkeypatch, image_to_data=_boom)
    monkeypatch.setattr("app.config.settings.ocr_engine", "tesseract")
    out = ocr_engine.ocr_frames(
        [Path("/tmp/a.jpg")], ["sessions/a/frames/frame_0001.jpg"], language=None
    )
    assert out[0]["text"] == ""
    assert out[0]["blocks"] == []
    assert out[0]["engine"] == "tesseract"


def test_tesseract_import_error_message(monkeypatch):
    """If pytesseract / Pillow are not installed, raise a clear ImportError."""
    monkeypatch.setattr("app.config.settings.ocr_engine", "tesseract")
    # Ensure imports fail.
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(ImportError, match="pytesseract / Pillow are not installed"):
        ocr_engine.ocr_frames(
            [Path("/tmp/a.jpg")], ["sessions/a/frames/frame_0001.jpg"], language=None
        )
