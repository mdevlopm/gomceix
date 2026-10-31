"""Per-user UI preferences (theme, colour scheme), stored atomically as JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path

from gomceix.i18n import LANGUAGES

from .theme import atomic_write_json

DEFAULTS = {"theme": "obsidian", "color_scheme": "system", "language": "system",
            "background": "none", "background_path": "", "background_dim": 0.25}
SCHEMES = ("system", "light", "dark")


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "gomceix" / "ui.json"


def load() -> dict:
    out = dict(DEFAULTS)
    try:
        data = json.loads(path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        if isinstance(data.get("theme"), str):
            out["theme"] = data["theme"]
        if data.get("color_scheme") in SCHEMES:
            out["color_scheme"] = data["color_scheme"]
        if data.get("language") == "system" or data.get("language") in LANGUAGES:
            out["language"] = data["language"]
        if isinstance(data.get("background"), str):
            out["background"] = data["background"]
        if isinstance(data.get("background_path"), str):
            out["background_path"] = data["background_path"]
        dim = data.get("background_dim")
        if isinstance(dim, (int, float)) and not isinstance(dim, bool) and 0 <= dim <= 1:
            out["background_dim"] = float(dim)
    return out


def save(prefs: dict) -> bool:
    try:
        atomic_write_json(path(), {k: prefs.get(k, v) for k, v in DEFAULTS.items()})
        return True
    except OSError:
        return False
