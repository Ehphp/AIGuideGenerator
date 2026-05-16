"""Phase E: deterministic, regex-based sanitizer for the privacy boundary.

The sanitizer rewrites raw timeline text into placeholder form
(`[CATEGORY_N]`) so that the external LLM only ever sees scrubbed content.
A `redaction_map` keeps the placeholder→original mapping locally so the
final guide can be rehydrated after the LLM responds.
"""
from app.sanitize.categories import DETECTORS, Detector
from app.sanitize.rehydrate import rehydrate_obj, rehydrate_text
from app.sanitize.sanitizer import SanitizationResult, Sanitizer

__all__ = [
    "DETECTORS",
    "Detector",
    "SanitizationResult",
    "Sanitizer",
    "rehydrate_obj",
    "rehydrate_text",
]
