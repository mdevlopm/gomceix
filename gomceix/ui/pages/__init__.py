"""Page registry. Each page module defines TITLE, ICON and build(win) -> Gtk.Widget.

`win` is the MainWindow: use win.controller (data), win.themes, win.prefs, win.toast(text).
Add a page by creating pages/<id>.py and listing <id> in ORDER.
"""
from importlib import import_module

ORDER = ("play", "library", "accounts", "saves", "requirements", "settings", "welcome", "setup")
# Reachable with `win.show_page(id)` but without a sidebar entry.
HIDDEN = frozenset({"welcome", "setup"})


def load():
    """Return [(id, title, icon, build)] in sidebar order."""
    out = []
    for pid in ORDER:
        mod = import_module(f"{__name__}.{pid}")
        out.append((pid, mod.TITLE, mod.ICON, mod.build))
    return out
