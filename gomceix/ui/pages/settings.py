from __future__ import annotations

import os

from gi.repository import Adw, Gtk

from gomceix import i18n

from .. import prefs
from .. import theme as theme_module
from ..widgets import button, row
from gomceix.controller.settings import resolve_choice
from ..files import ImageError, pick_image, store_background
from gomceix.i18n import _, N_

TITLE, ICON = N_("Settings"), "emblem-system-symbolic"

# Built-in theme names come from their JSON files; this lets the catalog translate them.
_BUILTIN_THEME_NAMES = (N_("System (Adwaita)"),)
_BACKGROUND_NAMES = (N_("None"), N_("Blocks"), N_("Horizon"), N_("Grid"), N_("Custom image…"))


def build(win):
    themes = win.themes
    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(title=_("Appearance"), description=_("Themes restyle the whole app instantly."))
    ids = themes.ids()
    theme_row = Adw.ComboRow(title=_("Theme"), model=Gtk.StringList.new([_(themes.themes[i].name) for i in ids]))
    theme_row.set_selected(ids.index(win.prefs["theme"]) if win.prefs["theme"] in ids else 0)
    scheme_row = Adw.ComboRow(title=_("Style (System theme only)"),
                              model=Gtk.StringList.new([_("Follow system"), _("Light"), _("Dark")]))
    scheme_row.set_selected(prefs.SCHEMES.index(win.prefs["color_scheme"]))

    def sync_sensitive():
        t = themes.themes.get(win.prefs["theme"])
        scheme_row.set_sensitive(t is None or t.scheme == "system")

    def changed(*_):
        win.prefs["theme"] = ids[theme_row.get_selected()]
        win.prefs["color_scheme"] = prefs.SCHEMES[scheme_row.get_selected()]
        themes.apply_prefs(win.prefs)
        sync_sensitive()
        prefs.save(win.prefs)

    language_values = ["system"] + list(i18n.LANGUAGES)
    language_row = Adw.ComboRow(
        title=_("Language"),
        model=Gtk.StringList.new([_("System default")] + list(i18n.LANGUAGES.values())))
    language_row.set_selected(language_values.index(win.prefs.get("language", "system"))
                              if win.prefs.get("language", "system") in language_values else 0)

    def language_changed(row_, _pspec):
        choice = language_values[row_.get_selected()]
        if choice == win.prefs.get("language"):
            return
        win.prefs["language"] = choice
        i18n.set_language(choice)
        prefs.save(win.prefs)
        win.retranslate()

    language_row.connect("notify::selected", language_changed)
    background_values = ["none", *theme_module.BUILTIN_BACKGROUNDS, "custom"]
    background_row = Adw.ComboRow(
        title=_("Background"), subtitle=_("Picture behind the banner on the Play page."),
        model=Gtk.StringList.new([_(n) for n in _BACKGROUND_NAMES]))
    current_bg = win.prefs.get("background", "none")
    background_row.set_selected(background_values.index(current_bg) if current_bg in background_values else 0)
    dim_row = Adw.SpinRow.new_with_range(0, 90, 5)
    dim_row.set_title(_("Darken the background"))
    dim_row.set_value(round(win.prefs.get("background_dim", 0.25) * 100))
    dim_row.set_visible(current_bg != "none")

    def apply_background():
        prefs.save(win.prefs)
        themes.apply_prefs(win.prefs)
        win.refresh_page("play")

    image_row = row(_("Image file"))
    choose_btn = button(_("Choose…"), "secondary", small=True)
    image_row.add_suffix(choose_btn)
    state = {"restoring": False}

    def refresh_image_row():
        path = win.prefs.get("background_path") or ""
        image_row.set_subtitle(os.path.basename(path) if path else _("No image chosen"))
        image_row.set_visible(win.prefs.get("background") == "custom")

    def select_combo(choice):
        state["restoring"] = True
        background_row.set_selected(background_values.index(choice) if choice in background_values else 0)
        state["restoring"] = False
        dim_row.set_visible(choice != "none")

    def choose_custom_image():
        previous = win.prefs.get("background", "none")

        def chosen(path):
            try:
                kept = store_background(path)
            except ImageError as exc:
                win.alert(_("Could not use that image"), str(exc))
                select_combo(previous)
                return
            win.prefs["background"], win.prefs["background_path"] = "custom", kept
            select_combo("custom")
            refresh_image_row()
            apply_background()

        pick_image(win, chosen, on_cancel=lambda: select_combo(previous))

    def background_changed(row_, _pspec):
        if state["restoring"]:
            return
        choice = background_values[row_.get_selected()]
        dim_row.set_visible(choice != "none")
        if choice == "custom" and not os.path.isfile(win.prefs.get("background_path") or ""):
            choose_custom_image()          # nothing kept yet: ask for a file first
            return
        if choice != win.prefs.get("background"):
            win.prefs["background"] = choice
            refresh_image_row()
            apply_background()

    def dim_changed(row_, _pspec):
        win.prefs["background_dim"] = row_.get_value() / 100
        prefs.save(win.prefs)
        themes.apply_prefs(win.prefs)        # live preview; the banner picks it up with the CSS

    background_row.connect("notify::selected", background_changed)
    dim_row.connect("notify::value", dim_changed)
    choose_btn.connect("clicked", lambda *_args: choose_custom_image())
    refresh_image_row()
    theme_row.connect("notify::selected", changed)
    scheme_row.connect("notify::selected", changed)
    sync_sensitive()
    group.add(language_row)
    group.add(theme_row)
    group.add(scheme_row)
    group.add(background_row)
    group.add(image_row)
    group.add(dim_row)
    page.add(group)
    for settings_group in win.controller.settings_groups():
        page.add(_settings_group(win, settings_group))
    about = Adw.PreferencesGroup(title=_("About"))
    from gomceix import __version__
    about.add(row(_("Gomceix {version}", version=__version__)))
    guide = row(_("Welcome guide"), _("Show the first-run guide again."))
    guide.set_activatable(True)
    guide.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    guide.connect("activated", lambda *_args: win.show_page("welcome"))
    about.add(guide)
    page.add(about)
    if themes.problems:
        warn = Adw.PreferencesGroup(title=_("Theme file problems"))
        for p in themes.problems:
            warn.add(row(p))
        page.add(warn)
    return page


def _settings_group(win, spec):
    """One group of launcher settings, drawn from the controller's description."""
    c = win.controller
    group = Adw.PreferencesGroup(title=spec.title, description=spec.description)
    for item in spec.items:
        current = c.get_setting(item.key)
        if item.kind == "switch":
            row_ = Adw.SwitchRow(title=item.title, subtitle=item.subtitle, use_markup=False)
            row_.set_active(bool(current))
            row_.connect("notify::active", lambda r, _p, key=item.key: c.set_setting(key, r.get_active()))

            def follow(payload, row_=row_, key=item.key):
                # The same setting flipped elsewhere (the Play page has a switch for it).
                if payload.get("key") == key and bool(payload.get("value")) != row_.get_active():
                    row_.set_active(bool(payload.get("value")))

            win.on("setting-changed", follow, owner="settings")
        elif item.kind == "choice":
            choices, selected = resolve_choice(item, current)
            values = [ch.value for ch in choices]
            row_ = Adw.ComboRow(title=item.title, subtitle=item.subtitle, use_markup=False,
                                model=Gtk.StringList.new([ch.label for ch in choices]))
            row_.set_selected(selected)
            row_.connect("notify::selected",
                         lambda r, _p, key=item.key, vals=values: c.set_setting(key, vals[r.get_selected()]))
        elif item.kind == "text":
            row_ = Adw.EntryRow(title=item.title, show_apply_button=True)
            row_.set_text(str(current or ""))
            row_.set_tooltip_text(item.subtitle or None)
            # Saved on Apply, not on every keystroke: each save is a disk write.
            row_.connect("apply", lambda r, key=item.key: c.set_setting(key, r.get_text().strip()))
        else:  # multiline
            row_ = _multiline_row(c, item, str(current or ""))
        group.add(row_)
    return group


def _multiline_row(controller, item, current):
    expander = Adw.ExpanderRow(title=item.title, subtitle=item.subtitle, use_markup=False)
    buffer = Gtk.TextBuffer(text=current)
    view = Gtk.TextView(buffer=buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
    view.add_css_class("monospace")
    frame = Gtk.ScrolledWindow(min_content_height=96, hscrollbar_policy=Gtk.PolicyType.NEVER)
    frame.set_child(view)
    apply_btn = button(_("Apply"), "primary", small=True, halign=Gtk.Align.END, margin_top=6)
    apply_btn.connect("clicked", lambda *_args: controller.set_setting(
        item.key, buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=8, margin_bottom=8,
                  margin_start=12, margin_end=12)
    box.append(frame)
    box.append(apply_btn)
    expander.add_row(box)
    return expander
