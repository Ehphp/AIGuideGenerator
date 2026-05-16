"""Utilities to normalize guide action verbs to a canonical vocabulary."""
from __future__ import annotations

CANONICAL_VERBS = {
    "OPEN",
    "NAVIGATE",
    "CLICK",
    "TYPE",
    "SELECT",
    "CONFIRM",
    "WAIT",
    "DOWNLOAD",
    "UPLOAD",
    "SCROLL",
    "VERIFY",
    "COPY",
    "PASTE",
    "CLOSE",
}

VERB_ALIASES: dict[str, str] = {
    "open": "OPEN",
    "launch": "OPEN",
    "start": "OPEN",
    "navigate": "NAVIGATE",
    "go to": "NAVIGATE",
    "goto": "NAVIGATE",
    "click": "CLICK",
    "press": "CLICK",
    "tap": "CLICK",
    "type": "TYPE",
    "enter": "TYPE",
    "input": "TYPE",
    "fill": "TYPE",
    "write": "TYPE",
    "select": "SELECT",
    "choose": "SELECT",
    "pick": "SELECT",
    "confirm": "CONFIRM",
    "submit": "CONFIRM",
    "approve": "CONFIRM",
    "ok": "CONFIRM",
    "wait": "WAIT",
    "download": "DOWNLOAD",
    "export": "DOWNLOAD",
    "upload": "UPLOAD",
    "import": "UPLOAD",
    "scroll": "SCROLL",
    "verify": "VERIFY",
    "check": "VERIFY",
    "ensure": "VERIFY",
    "validate": "VERIFY",
    "copy": "COPY",
    "paste": "PASTE",
    "close": "CLOSE",
    "dismiss": "CLOSE",
}


def normalize_verb(verb: str) -> str:
    text = str(verb or "").strip().lower()
    if not text:
        return ""

    for alias in sorted(VERB_ALIASES.keys(), key=len, reverse=True):
        if text == alias or text.startswith(alias + " "):
            return VERB_ALIASES[alias]

    return text.upper()


def normalize_guide_dict(data: dict) -> dict:
    steps = data.get("steps")
    if not isinstance(steps, list):
        return data

    for step in steps:
        if not isinstance(step, dict):
            continue
        actions = step.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            verb = action.get("verb")
            if isinstance(verb, str):
                normalized = normalize_verb(verb)
                if normalized:
                    action["verb"] = normalized

    return data
