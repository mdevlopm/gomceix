from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402
from gomceix.i18n import _, N_

from ..widgets import button

TITLE, ICON = N_("Welcome"), "starred-symbolic"

STEP_TAGS = ("welcome", "signin", "download", "ready")


def _dots():
    """A row of one dot per step; the current one is accented."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                  halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=24)
    labels = [Gtk.Label(label="●") for _tag in STEP_TAGS]
    for l in labels:
        box.append(l)
    return box, labels


def _set_dots(labels, active: int):
    for i, l in enumerate(labels):
        if i == active:
            if not l.has_css_class("accent"):
                l.add_css_class("accent")
            if l.has_css_class("dim-label"):
                l.remove_css_class("dim-label")
        else:
            if not l.has_css_class("dim-label"):
                l.add_css_class("dim-label")
            if l.has_css_class("accent"):
                l.remove_css_class("accent")


def _button(label, cb) -> Gtk.Button:
    b = button(label, "primary", halign=Gtk.Align.CENTER)
    b.connect("clicked", cb)
    return b


def _step(view, tag: str, title: str, description: str, child=None):
    """One flow step: its own header bar (NavigationView shows the back
    arrow in it automatically once the page has been pushed onto the stack)
    over a StatusPage (title + description + optional child), with a
    progress-dot row pinned at the bottom of the page."""
    status = Adw.StatusPage(title=title, description=description)
    status.set_vexpand(True)
    if child is not None:
        status.set_child(child)
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    inner.append(status)
    dots, labels = _dots()
    inner.append(dots)
    body = Adw.ToolbarView()
    # No title here: the window's header already names the page, so a second
    # title would repeat it. This bar only carries the NavigationView back arrow.
    header = Adw.HeaderBar(title_widget=Gtk.Label())
    header.add_css_class("flat")
    # The window's real controls live on the split view's own header bar;
    # painting them again here would duplicate them under the first row.
    # The NavigationView back arrow is not a title button and is unaffected.
    header.set_show_end_title_buttons(False)
    body.add_top_bar(header)
    body.set_content(inner)
    page = Adw.NavigationPage(child=body, tag=tag, title=title)
    view.add(page)
    return labels


def build(win):
    view = Adw.NavigationView()
    labels_by_step = {}

    labels_by_step["welcome"] = _step(
        view, "welcome", _("Welcome"),
        _("Gomceix runs Minecraft Bedrock Edition on your Linux desktop."),
        child=_button(_("Get started"), lambda *_args: view.push_by_tag("signin")))

    labels_by_step["signin"] = _step(
        view, "signin", _("Store sign-in"),
        _("Sign in with the Microsoft account that owns Minecraft. This lets Gomceix download the game."),
        child=_button(_("Sign in"), lambda *_args: win.controller.sign_in_store()))

    c = win.controller
    group = Adw.PreferencesGroup()
    version_row = Adw.ComboRow(title=_("Version"), model=Gtk.StringList.new([]))
    group.add(version_row)
    shown = {"versions": [], "filling": False, "unreachable": False}

    def fill_versions(*_args):
        """Show the controller's versions with its selection. The catalogue loads in
        the background, so on a first run this page exists before there is anything
        to list: fill it again when the list arrives."""
        shown["versions"] = versions = list(c.versions())
        shown["unreachable"] = unreachable = c.catalog_loaded() and not versions and c.catalog_failed()
        empty = (_("Could not reach the version list. Check your connection.") if unreachable
                 else _("No {channel} versions found", channel=_(c.channel())) if c.catalog_loaded()
                 else _("Loading versions…"))
        shown["filling"] = True                      # swapping the model "selects" row 0: not the user's doing
        try:
            version_row.set_model(Gtk.StringList.new(versions or [empty]))
            if versions:
                selected = c.selected_version()
                version_row.set_selected(versions.index(selected) if selected in versions else 0)
        finally:
            shown["filling"] = False
        version_row.set_sensitive(bool(versions))
        install_btn.set_label(_("Try again") if unreachable else _("Install now"))     # offline: the button fetches the list again
        install_btn.set_sensitive(bool(versions) or unreachable)

    def chosen(row_, _pspec):
        versions = shown["versions"]
        index = row_.get_selected()
        if not shown["filling"] and 0 <= index < len(versions):
            c.set_version(versions[index])          # Install now installs what this list shows

    def install_now(*_args):
        if shown["unreachable"]:
            c.reload_catalog()
            return
        c.install(win.toast)
        if c.state != "idle":
            win.show_page("setup")

    dl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                     valign=Gtk.Align.CENTER)
    dl_box.append(group)
    install_btn = _button(_("Install now"), install_now)
    dl_box.append(install_btn)
    fill_versions()
    version_row.connect("notify::selected", chosen)
    win.on("catalog-changed", fill_versions, owner="welcome")
    win.on("setting-rejected", fill_versions, owner="welcome")      # a version that was not saved
    labels_by_step["download"] = _step(
        view, "download", _("Choose a version"), _("Gomceix downloads and prepares it for you."), child=dl_box)

    labels_by_step["ready"] = _step(
        view, "ready", _("Ready"), _("You are ready to play."),
        child=_button(_("Open Play"), lambda *_args: win.show_page("play")))

    def on_visible(v, _pspec):
        page = v.get_visible_page()
        if page is None:
            return
        active = STEP_TAGS.index(page.get_tag())
        for labels in labels_by_step.values():
            _set_dots(labels, active)

    def on_store_login(payload):
        if payload.get("state") == "done" and view.get_visible_page().get_tag() == "signin":
            view.push_by_tag("download")      # the sign-in window finished: move on by itself

    win.on("store-login", on_store_login, owner="welcome")
    view.connect("notify::visible-page", on_visible)
    # replace_with_tags() below sets the first visible page; styling must be
    # in place before (or right after) that, or every dot renders unstyled.
    for labels in labels_by_step.values():
        _set_dots(labels, 0)
    view.replace_with_tags(["welcome"])
    return view
