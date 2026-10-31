"""Theme engine: JSON design tokens -> CSS overrides of libadwaita's named colours.

The pure parts (loading, validation, CSS generation) import no GTK, so they are
unit-testable without a display. `ThemeManager.apply` imports GTK lazily.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1
BUILTIN_DIR = Path(__file__).with_name("themes")
DEFAULT_THEME_ID = "adwaita"

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# token name -> default (used when a theme leaves it out and it is not "adwaita")
COLOR_KEYS = ("accent", "window", "view", "card", "header", "sidebar", "popover",
              "fg", "success", "warning", "error")
SHAPE_LIMITS = {"radius": (0, 32), "spacing": (4, 32)}
SCHEMES = ("light", "dark", "system")
STYLES = ("flat", "glass", "glow")   # surface finish; see css_for


class ThemeError(Exception):
    """A theme file cannot be used at all."""


@dataclass
class Theme:
    id: str
    name: str
    scheme: str                       # light | dark | system
    colors: dict = field(default_factory=dict)
    radius: int = 14
    spacing: int = 12
    background: dict = field(default_factory=dict)
    style: str = "flat"
    warnings: list = field(default_factory=list)

    @property
    def overrides_colors(self) -> bool:
        return bool(self.colors)


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def on_color(hex_color: str) -> str:
    """Readable foreground (black or white) for a coloured surface."""
    return "#000000" if _luminance(hex_color) > 0.45 else "#ffffff"


def parse_theme(data, source: str = "<memory>") -> Theme:
    """Validate a decoded theme dict. Bad values are dropped with a warning;
    only a structurally unusable file raises ThemeError."""
    if not isinstance(data, dict):
        raise ThemeError(f"{source}: theme must be a JSON object")
    if data.get("schema", SCHEMA) != SCHEMA:
        raise ThemeError(f"{source}: unsupported schema {data.get('schema')!r} (expected {SCHEMA})")
    tid = data.get("id")
    if not isinstance(tid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", tid):
        raise ThemeError(f"{source}: 'id' must be 1-40 chars of a-z, 0-9, '-' or '_'")
    scheme = data.get("scheme", "system")
    if scheme not in SCHEMES:
        raise ThemeError(f"{source}: 'scheme' must be one of {', '.join(SCHEMES)}")
    theme = Theme(id=tid, name=str(data.get("name") or tid)[:60], scheme=scheme)

    style = data.get("style", "flat")
    if style in STYLES:
        theme.style = style
    else:
        theme.warnings.append(f"style {style!r} is not one of {', '.join(STYLES)}; 'flat' used")

    raw_colors = data.get("colors", {})
    if not isinstance(raw_colors, dict):
        theme.warnings.append("'colors' must be an object; ignored")
        raw_colors = {}
    for key, val in raw_colors.items():
        if key not in COLOR_KEYS:
            theme.warnings.append(f"unknown colour token {key!r} ignored")
        elif not isinstance(val, str) or not _HEX.match(val):
            theme.warnings.append(f"colour {key!r}={val!r} is not a hex colour; ignored")
        else:
            theme.colors[key] = val.lower()
    if theme.colors and scheme == "system":
        theme.warnings.append("a theme that sets colours should declare 'light' or 'dark'")

    shape = data.get("shape", {})
    if isinstance(shape, dict):
        for key, (lo, hi) in SHAPE_LIMITS.items():
            if key in shape:
                v = shape[key]
                if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
                    setattr(theme, key, v)
                else:
                    theme.warnings.append(f"shape.{key}={v!r} outside {lo}-{hi}; default kept")
    bg = data.get("background", {})
    if isinstance(bg, dict):
        blur, dim = bg.get("blur", 0), bg.get("dim", 0.0)
        theme.background = {
            "image": bg.get("image") if isinstance(bg.get("image"), str) else None,
            "blur": blur if isinstance(blur, (int, float)) and 0 <= blur <= 40 else 0,
            "dim": dim if isinstance(dim, (int, float)) and 0 <= dim <= 1 else 0.0,
        }
    return theme


def load_theme(path) -> Theme:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ThemeError(f"{path.name}: {exc}") from exc
    return parse_theme(data, path.name)


BACKGROUNDS_DIR = Path(__file__).with_name("backgrounds")
BUILTIN_BACKGROUNDS = ("blocks", "horizon", "grid")
MAX_DIM = 0.9


def background_spec(user_prefs: dict):
    """{"url", "dim"} for the home banner's background, or None for no image.

    `background` is "none", a built-in id or "custom" (then `background_path`);
    a missing or unreadable file means no image, never an error.
    """
    choice = user_prefs.get("background", "none")
    if choice in BUILTIN_BACKGROUNDS:
        path = BACKGROUNDS_DIR / f"{choice}.svg"
    elif choice == "custom":
        path = Path(str(user_prefs.get("background_path") or ""))
    else:
        return None
    try:
        if not path.is_file():
            return None
        url = path.resolve().as_uri()
    except (OSError, ValueError):
        return None
    try:
        dim = float(user_prefs.get("background_dim", 0.25))
    except (TypeError, ValueError):
        dim = 0.25
    return {"url": url, "dim": min(max(dim, 0.0), MAX_DIM)}


def css_for(theme: Theme, background: dict | None = None) -> str:
    """CSS that restyles libadwaita through its documented named colours.
    `background` (see background_spec) layers an image under the banner's accent
    gradient, darkened by `dim`."""
    c = theme.colors
    lines = []

    def define(name, value):
        lines.append(f"@define-color {name} {value};")

    if c:
        accent = c.get("accent")
        if accent:
            define("accent_bg_color", accent)
            define("accent_color", accent)
            define("accent_fg_color", on_color(accent))
        for token, names in (
            ("window", ("window_bg_color", "view_bg_color")),
            ("view", ("view_bg_color",)),
            ("card", ("card_bg_color",)),
            ("header", ("headerbar_bg_color", "headerbar_backdrop_color")),
            ("sidebar", ("sidebar_bg_color", "sidebar_backdrop_color")),
            ("popover", ("popover_bg_color",)),
        ):
            if token in c:
                for n in names:
                    define(n, c[token])
        if "fg" in c:
            for n in ("window_fg_color", "view_fg_color", "card_fg_color", "headerbar_fg_color",
                      "popover_fg_color", "sidebar_fg_color"):
                define(n, c["fg"])
        for token in ("success", "warning", "error"):
            if token in c:
                define(f"{token}_bg_color", c[token])
                define(f"{token}_color", c[token])
                define(f"{token}_fg_color", on_color(c[token]))
    lines.append(f".gx-hero {{ border-radius: {theme.radius + 10}px; }}")
    lines.append(f".gx-card, .gx-tile {{ border-radius: {theme.radius}px; }}")
    if theme.style == "glass":
        lines.append(".gx-card, .gx-tile { background-color: alpha(@card_bg_color, 0.55); "
                     "border: 1px solid alpha(@window_fg_color, 0.14); }")
    elif theme.style == "glow":
        lines.append(".gx-card, .gx-tile { border: 1px solid alpha(@accent_bg_color, 0.22); "
                     "box-shadow: 0 0 22px alpha(@accent_bg_color, 0.07); }")
        lines.append(".gx-tile:hover { border-color: alpha(@accent_bg_color, 0.55); "
                     "box-shadow: 0 0 26px alpha(@accent_bg_color, 0.18); }")
        lines.append("popover.background > contents { border-color: alpha(@accent_bg_color, 0.38); "
                     "box-shadow: 0 18px 44px alpha(black, 0.55), 0 0 26px alpha(@accent_bg_color, 0.14); }")
    if background:
        dim = background["dim"]
        lines.append(
            ".gx-hero { background-image: "
            f"linear-gradient(alpha(black, {dim}), alpha(black, {dim})), "
            f'url("{background["url"]}"), '
            "linear-gradient(135deg, alpha(@accent_bg_color, 0.30), alpha(@card_bg_color, 0.92)); "
            "background-size: auto, cover, auto; background-position: center; background-repeat: no-repeat; }")
    lines.append(f".gx-page {{ padding: {theme.spacing * 2}px; }}")
    return "\n".join(lines) + "\n"


def user_theme_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "gomceix" / "themes"


def discover(extra_dirs=()):
    """Return (themes: dict id->Theme, problems: list[str]); user themes override built-ins."""
    themes, problems = {}, []
    for directory in (BUILTIN_DIR, user_theme_dir(), *map(Path, extra_dirs)):
        if not directory.is_dir():
            continue
        for p in sorted(directory.glob("*.json")):
            try:
                t = load_theme(p)
            except ThemeError as exc:
                problems.append(str(exc))
                continue
            problems.extend(f"{p.name}: {w}" for w in t.warnings)
            themes[t.id] = t
    if DEFAULT_THEME_ID not in themes:
        themes[DEFAULT_THEME_ID] = Theme(DEFAULT_THEME_ID, "System", "system")
    return themes, problems


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ThemeManager:
    """Applies a theme to the running GTK display. GTK is imported lazily."""

    def __init__(self, extra_dirs=()):
        self.themes, self.problems = discover(extra_dirs)
        self.current_id = DEFAULT_THEME_ID
        self._provider = None
        self._base_provider = None

    def ids(self):
        return sorted(self.themes, key=lambda i: (i != DEFAULT_THEME_ID, self.themes[i].name.lower()))

    def apply_prefs(self, user_prefs: dict) -> Theme:
        """Apply theme, colour scheme and background exactly as the preferences say."""
        return self.apply(user_prefs.get("theme", DEFAULT_THEME_ID),
                          system_scheme=user_prefs.get("color_scheme", "system"),
                          background=background_spec(user_prefs))

    def apply(self, theme_id: str, *, system_scheme: str = "system", background=None) -> Theme:
        """Apply `theme_id` (falls back to the default if unknown). `system_scheme`
        (system|light|dark) only matters for themes that declare scheme 'system'."""
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gtk

        theme = self.themes.get(theme_id) or self.themes[DEFAULT_THEME_ID]
        display = Gdk.Display.get_default()
        manager = Adw.StyleManager.get_default()
        scheme = theme.scheme if theme.scheme != "system" else system_scheme
        manager.set_color_scheme({"light": Adw.ColorScheme.FORCE_LIGHT,
                                  "dark": Adw.ColorScheme.FORCE_DARK}.get(scheme, Adw.ColorScheme.DEFAULT))
        if self._base_provider is None:
            self._base_provider = Gtk.CssProvider()
            self._base_provider.load_from_path(str(Path(__file__).with_name("style.css")))
            Gtk.StyleContext.add_provider_for_display(display, self._base_provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if self._provider is None:
            self._provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(display, self._provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._provider.load_from_string(css_for(theme, background))
        self.current_id = theme.id
        return theme
