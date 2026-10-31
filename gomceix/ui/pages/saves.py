from __future__ import annotations

from gi.repository import Adw

from ..widgets import row
from gomceix.i18n import _, N_

TITLE, ICON = N_("Saves & Content"), "document-save-symbolic"


def _size_text(size_mb: int) -> str:
    """Human size: MB until 1024, then GB with one decimal (1280 -> 1.2 GB)."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f} GB"
    return f"{size_mb} MB"


def _subtitle(save) -> str:
    parts = [] if save.size_mb is None else [_size_text(save.size_mb)]
    if save.edition:
        parts.append(save.edition)
    parts.append(save.last_played)
    return "  ·  ".join(parts)


def _worlds_group(win, saves) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title=_("Worlds"))
    for save in saves:
        r = row(save.name, _subtitle(save))
        group.add(r)
    return group


def build(win):
    saves = win.controller.saves()
    if not saves:
        return Adw.StatusPage(icon_name="folder-symbolic", title=_("No worlds yet"),
                              description=_("Worlds you play will show up here."))

    page = Adw.PreferencesPage()
    page.add(_worlds_group(win, saves))
    return page
