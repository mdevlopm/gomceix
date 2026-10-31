from __future__ import annotations

from gi.repository import GLib, Gtk, Pango

from ..textfit import VERSION_SIZE_CLASSES, version_size_class
from ..widgets import ChoiceButton, Segmented, animate, fade_in, scrolled_clamp
from gomceix.i18n import _, N_

TITLE, ICON = N_("Play"), "media-playback-start-symbolic"

CHANNELS = (N_("Stable"), N_("Preview"))


def _gib(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GB"


def _tile(label: str, widget: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
    box.add_css_class("gx-tile")
    caption = Gtk.Label(label=label.upper(), xalign=0)
    caption.add_css_class("gx-tile-label")
    box.append(caption)
    box.append(widget)
    # The caption is the control's name for a screen reader (the control alone reads "switch" / "menu").
    # (LABELLED_BY needs a GList pointer that Python cannot pass: GTK rejects the call.)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])
    return box


def selection_index(versions, selected) -> int:
    """Where `selected` sits in `versions`; 0 when it is not there. The catalogue is
    replaced by a background thread, so the list and the selection read a moment
    apart can disagree: that must never break the page."""
    return versions.index(selected) if selected in versions else 0


def build(win):
    c = win.controller
    versions = c.versions()
    loaded = c.catalog_loaded()
    selected = c.selected_version() if versions else ""
    unreachable = loaded and not versions and c.catalog_failed()      # offline: PLAY becomes "Try again"

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                  margin_top=20, margin_bottom=24, margin_start=16, margin_end=16)

    # ---- mode: who signs the game in
    mode = c.mode()
    host, port = c.proxy_destination()
    def on_mode(value):
        c.set_mode(value)
        if c.mode() != value:        # refused (a game is starting): show the truth again
            GLib.idle_add(lambda: (win.refresh_page("play"), False)[1])

    seg = Segmented([("xodus", _("Normal")), ("proxypass", _("ProxyPass"))], mode, on_mode)
    note = Gtk.Label(xalign=0, wrap=True)
    note.add_css_class("gx-mode-note")
    note.set_label(_("The launcher signs the game in with your Microsoft account.") if mode == "xodus"
                   else _("ProxyPass has no build for this version, so the game starts without it.") if c.proxy_skipped()
                   else _("In the game, open the ProxyPass world on the Worlds tab. It leads to {host}:{port}.", host=host, port=port))
    mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    mode_box.append(seg)
    mode_box.append(note)
    problem = c.proxy_problem()
    # ProxyPass mode lists only the versions it can play; a saved choice outside that
    # list stays shown (and warned about) until the player picks one from the list.
    outside_list = bool(versions) and mode == "proxypass" and bool(c.proxy_supported()) and selected not in versions
    if problem:
        warning = Gtk.Label(xalign=0, wrap=True, label=problem)
        warning.add_css_class("warning")
        mode_box.append(warning)
    box.append(mode_box)

    # ---- hero: what you are about to play, and the one big button
    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    hero.add_css_class("gx-hero")
    overline = Gtk.Label(label=_("MINECRAFT · BEDROCK EDITION"), xalign=0)
    overline.add_css_class("gx-overline")
    # Long build names (a preview such as "26.100.123.7-preview", or odd data) must not widen the
    # whole window: shrink the number step by step and ellipsize as a last resort.
    version_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
    version_label.add_css_class("gx-version")

    def show_version(text: str):
        for css in VERSION_SIZE_CLASSES:
            version_label.remove_css_class(css)
        if version_size_class(text):
            version_label.add_css_class(version_size_class(text))
        version_label.set_label(text)
        version_label.set_tooltip_text(text if len(text) > 14 else None)

    if outside_list:
        show_version(selected)
    elif versions:
        show_version(versions[selection_index(versions, selected)])
    else:
        version_label.set_label("…" if not loaded else "—")
        version_label.add_css_class("dim-label")

    chips = Gtk.Box(spacing=8, halign=Gtk.Align.START)
    channel_chip = Gtk.Label(label=_(c.channel()))
    channel_chip.add_css_class("gx-chip")
    chips.append(channel_chip)
    ms = next((a for a in c.accounts() if a.kind in ("microsoft", "proxypass")), None)
    account_chip = Gtk.Label(label=(f"● {ms.name or _('Signed in')}" if ms and ms.signed_in else _("Not signed in")),
                             ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
    account_chip.add_css_class("gx-chip")
    if not (ms and ms.signed_in):
        account_chip.add_css_class("muted")
    chips.append(account_chip)

    play = Gtk.Button(halign=Gtk.Align.START, margin_top=22)
    play.add_css_class("pill")
    play.add_css_class("gx-play")
    status = Gtk.Label(label="", xalign=0, wrap=True, margin_top=6)
    status.add_css_class("dim-label")
    bar = Gtk.ProgressBar(visible=False, hexpand=True, margin_top=10)
    bar.add_css_class("gx-bar")
    for w in (overline, version_label, chips, play, status, bar):
        hero.append(w)
    box.append(hero)

    # ---- tiles: version / channel / launcher behaviour
    version_dd = ChoiceButton(versions or ["—"], -1 if outside_list else selection_index(versions, selected),
                              lambda i: on_version(i), placeholder=selected if outside_list else "")
    channel_dd = ChoiceButton([_(n) for n in CHANNELS], CHANNELS.index(c.channel()),
                              lambda i: c.set_channel(CHANNELS[i]))   # emits catalog-changed → page rebuilds
    close = Gtk.Switch(active=c.close_on_launch(), halign=Gtk.Align.START, valign=Gtk.Align.CENTER, margin_top=6)
    tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=12,
                        row_spacing=12, min_children_per_line=1, max_children_per_line=3)
    for t in (_tile(_("Version"), version_dd), _tile(_("Channel"), channel_dd),
              _tile(_("Close on launch"), close)):
        tiles.append(t)
    box.append(tiles)

    # ---- reflect the controller's session state on the button, status and bar
    def show_state(state: str, message: str = ""):
        busy = state != "idle"
        for cls in ("suggested-action", "destructive-action"):
            play.remove_css_class(cls)
        if state == "running":
            play.set_label(_("STOP"))
            play.add_css_class("destructive-action")
            play.set_sensitive(True)
        elif state == "idle":
            play.set_label(_("Try again") if unreachable else _("PLAY"))
            play.add_css_class("suggested-action")
            play.set_sensitive(unreachable or (bool(versions) and not problem))
        else:
            play.set_label(_("Preparing…") if state == "preparing" else _("Stopping…"))
            play.add_css_class("suggested-action")
            play.set_sensitive(False)
        seg.set_sensitive(not busy)
        channel_dd.set_sensitive(not busy)
        version_dd.set_sensitive(not busy and bool(versions))
        if busy:
            status.set_label(message)
        elif not versions:
            status.set_label(_("Loading versions…") if not loaded
                             else _("Could not reach the version list. Check your connection.") if unreachable
                             else _("No {channel} versions found", channel=_(c.channel())))
        else:
            status.set_label("")
        bar.set_visible(state == "preparing")

    def on_progress(payload):
        done, total = payload.get("done") or 0, payload.get("total") or 0
        bar.set_visible(True)
        if total > 0:
            target = min(done / total, 1.0)
            animate(bar, bar.get_fraction(), target, 300, bar.set_fraction)
            status.set_label(_("Downloading… {done} of {total}", done=_gib(done), total=_gib(total)))
        else:
            bar.pulse()

    def on_state(payload):
        show_state(payload.get("state", "idle"), payload.get("message", ""))

    def on_play(_btn):
        if c.state == "running":
            c.stop()
            return
        if unreachable:
            c.reload_catalog()
            return
        first_install = c.install_needed() and bool(versions)
        c.play(win.toast)
        if first_install and c.state != "idle":
            win.show_page("setup")        # a first install gets the full setup screen (only if it began)

    def on_version(index):
        if versions and index < len(versions):
            c.set_version(versions[index])
            show_version(versions[index])
            if mode == "proxypass":                      # which versions ProxyPass can play decides the PLAY button
                GLib.idle_add(lambda: (win.refresh_page("play"), False)[1])

    play.connect("clicked", on_play)
    close.connect("notify::active", lambda sw, _p: c.set_close_on_launch(sw.get_active()))

    def on_setting(payload):
        # Changed on the Settings page (or by another window of the same switch): follow it.
        if payload.get("key") == "close_on_launch" and bool(payload.get("value")) != close.get_active():
            close.set_active(bool(payload.get("value")))

    win.on("setting-changed", on_setting, owner="play")
    win.on("play-state", on_state, owner="play")
    win.on("proxy-support-changed", lambda _p: win.refresh_page("play"), owner="play")
    win.on("progress", on_progress, owner="play")
    show_state(c.state, getattr(win, "play_message", ""))
    fade_in(mode_box, 350)
    fade_in(hero, 450, delay=60)
    fade_in(tiles, 450, delay=140)
    return scrolled_clamp(box)
