from __future__ import annotations

from gi.repository import Adw, Gtk

from ..widgets import menu_item, row
from gomceix.i18n import _, N_

TITLE, ICON = N_("Library"), "folder-symbolic"


def _size_text(size_mb: int) -> str:
    """Human size: MB until 1024, then GB with one decimal (1280 -> 1.2 GB)."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f} GB"
    return f"{size_mb} MB"


def _subtitle(build) -> str:
    text = _(build.channel) if build.size_mb is None else f"{_(build.channel)} · {_size_text(build.size_mb)}"
    if build.in_use:
        text += " · " + _("in use")
    return text


def _prefix(build) -> Gtk.Widget:
    if build.selected:
        icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
        icon.set_valign(Gtk.Align.CENTER)
        return icon
    spacer = Gtk.Box()
    spacer.set_size_request(16, -1)
    spacer.set_valign(Gtk.Align.CENTER)
    return spacer


def _confirm_remove(win, version: str, path: str) -> None:
    dialog = Adw.AlertDialog(
        heading=_("Remove Minecraft {version}?", version=version),
        body=_("Worlds and settings are kept; only the downloaded game files are deleted."))
    dialog.set_heading_use_markup(False)
    dialog.set_body_use_markup(False)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("remove", _("Remove"))
    dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect(
        "response",
        lambda _dialog, answer: (win.controller.remove_build(path), win.toast(_("Removing Minecraft {version}…", version=version))) if answer == "remove" else None)
    dialog.present(win)


def _menu(win, build) -> Gtk.MenuButton:
    menu = Gtk.MenuButton(icon_name="view-more-symbolic")
    menu.add_css_class("flat")
    menu.set_valign(Gtk.Align.CENTER)
    label = _("Actions for Minecraft {version}", version=build.version)
    menu.set_tooltip_text(label)                      # an icon-only button needs a name for keyboard and screen-reader users
    menu.update_property([Gtk.AccessibleProperty.LABEL], [label])

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    use = menu_item(_("Use this version"), "object-select-symbolic")
    use.set_visible(not build.selected)
    use.connect("clicked", lambda *_args: ((win.controller.use_build(build.tag, build.channel), win.toast(_("Minecraft {version} will start next time.", version=build.version))),
                                       menu.get_popover().popdown()))
    box.append(use)

    remove = menu_item(_("Remove…"), "user-trash-symbolic", danger=True)
    remove.set_sensitive(not build.in_use and bool(build.path))   # no folder known: nothing safe to delete
    remove.connect("clicked", lambda *_args: (menu.get_popover().popdown(),
                                          _confirm_remove(win, build.version, build.path)))
    box.append(remove)

    popover = Gtk.Popover()
    popover.set_child(box)
    menu.set_popover(popover)
    return menu


def _versions_group(win, builds) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title=_("Installed versions"))
    for build in builds:
        result = row(_("Minecraft {version}", version=build.version), _subtitle(build))
        result.add_prefix(_prefix(build))
        result.add_suffix(_menu(win, build))
        group.add(result)
    return group


def _add_group(win) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title=_("Add"))
    add = row(_("Install another version…"))
    add.set_activatable(True)
    add.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    add.connect("activated", lambda *_args: (win.show_page("play"), win.toast(_("Pick a version on the Play page, then press Play to download it."))))
    group.add(add)
    return group


def build(win):
    builds = win.controller.builds()
    if not builds:
        empty = Adw.StatusPage(icon_name="folder-symbolic", title=_("No versions installed"),
                               description=_("Install a version to start playing."))
        empty.set_child(_add_group(win))
        return empty

    page = Adw.PreferencesPage()
    page.add(_versions_group(win, builds))
    page.add(_add_group(win))
    return page
