"""Translations: tiny, dependency-free, no build step.

A catalog is a JSON map ``{"English text": "translation"}`` in
``gomceix/locales/<code>.json``; English is the source language and needs no
file. ``_("text")`` returns the translation (or the text itself when there is
none); keyword arguments fill ``{name}`` placeholders after translating, so one
catalog entry serves every value. ``N_("text")`` only marks a string for
extraction (use it for constants such as page titles, translate at display time).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LOCALES_DIR = Path(__file__).with_name("locales")
SOURCE = "en"
# code -> name in its own language, shown in the language picker
LANGUAGES = {"en": "English", "tr": "Türkçe", "zh": "中文"}

_catalog: dict = {}
_language = SOURCE


def N_(text: str) -> str:
    """Mark `text` for translation without translating it now."""
    return text


def _(text: str, **fields) -> str:
    translated = _catalog.get(text, text)
    if not fields:
        return translated
    try:
        return translated.format(**fields)
    except (KeyError, IndexError, ValueError):
        # A bad translation must never break the screen: fall back to the source.
        return text.format(**fields)


def language() -> str:
    return _language


def detect(environ=None) -> str:
    """The first supported language the environment asks for, else English.

    Reads LANGUAGE (a colon-separated preference list), then LC_ALL,
    LC_MESSAGES and LANG. Neutral locales (C, POSIX) say nothing and are
    skipped; an unsupported language does NOT end the search: ``fr:tr`` is Turkish.
    """
    env = os.environ if environ is None else environ
    candidates = []
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        candidates.extend((env.get(name) or "").split(":"))
    for candidate in candidates:
        code = candidate.strip().lower().replace("-", "_")
        code = code.split(".")[0].split("@")[0]
        if not code or code in ("c", "posix"):
            continue
        short = code.split("_")[0]
        if short in LANGUAGES:
            return short
    return SOURCE


def load_catalog(code: str) -> dict:
    """The catalog for `code`; empty for English or when the file is unusable."""
    if code == SOURCE:
        return {}
    try:
        data = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def set_language(choice: str, environ=None) -> str:
    """Select `choice` ("system" or a language code); returns the code in effect."""
    global _catalog, _language
    code = detect(environ) if choice in ("", "system") else (choice if choice in LANGUAGES else SOURCE)
    _catalog = load_catalog(code)
    _language = code
    return code
