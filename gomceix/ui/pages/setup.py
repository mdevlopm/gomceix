"""Setup screen: installs the game and its runtime, step by step, with live progress."""
from __future__ import annotations

from gi.repository import Adw, Gtk

from gomceix.controller.setup_steps import STEPS, overall, steps_for
from gomceix.i18n import _, N_

from ..widgets import ProgressRing, button, fade_in

TITLE, ICON = N_("Setup"), "document-save-symbolic"


def _gib(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GB"


def build(win):
    c = win.controller
    ring = ProgressRing(size=220, thickness=12)
    percent = Gtk.Label(label="0%")
    percent.add_css_class("gx-percent")
    overlay = Gtk.Overlay(child=ring, halign=Gtk.Align.CENTER)
    overlay.add_overlay(percent)
    percent.set_halign(Gtk.Align.CENTER)
    percent.set_valign(Gtk.Align.CENTER)

    title = Gtk.Label(label=_("Set up Minecraft"), wrap=True, justify=Gtk.Justification.CENTER)
    title.add_css_class("gx-setup-title")
    subtitle = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
    subtitle.add_css_class("dim-label")

    rows = {}
    steps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8)
    for sid, label, _share in STEPS:
        row = Gtk.Box(spacing=12)
        row.add_css_class("gx-step")
        icon = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, width_request=22)
        icon.add_named(Gtk.Image.new_from_icon_name("radio-symbolic"), "pending")
        icon.add_named(Gtk.Spinner(spinning=True), "active")
        check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        check.add_css_class("gx-check")
        icon.add_named(check, "done")
        text = Gtk.Label(label=_(label), xalign=0, hexpand=True)
        text.add_css_class("gx-step-title")
        row.append(icon)
        row.append(text)
        steps_box.append(row)
        rows[sid] = (row, icon)

    action = button("", "primary", halign=Gtk.Align.CENTER, margin_top=8)

    state = {"stage": None, "phase": "idle"}   # idle | running | done

    def mark(stage):
        order = [s[0] for s in steps_for(c.mode())]
        for sid, (row, _icon) in rows.items():
            row.set_visible(sid in order)
        at = order.index(stage) if stage in order else -1
        for i, sid in enumerate(order):
            row, icon = rows[sid]
            for cls in ("active", "done"):
                row.remove_css_class(cls)
            if at < 0 or i > at:
                icon.set_visible_child_name("pending")
            elif i == at:
                row.add_css_class("active")
                icon.set_visible_child_name("active")
            else:
                row.add_css_class("done")
                icon.set_visible_child_name("done")

    def set_phase(phase):
        state["phase"] = phase
        if phase == "idle":
            title.set_label(_("Set up Minecraft"))
            subtitle.set_label(_("Gomceix downloads the game and its engine once. Keep this window open."))
            action.set_label(_("Install now"))
            action.set_visible(True)
            mark(None)
            ring.set_fraction(0.0)
            percent.set_label("0%")
        elif phase == "running":
            title.set_label(_("Installing Minecraft {version}", version=c.selected_version()))
            action.set_visible(False)
        else:
            title.set_label(_("All set"))
            subtitle.set_label(_("Minecraft is ready."))
            action.set_label(_("Go to Play"))
            action.set_visible(True)
            for sid in [x[0] for x in steps_for(c.mode())]:
                rows[sid][0].remove_css_class("active")
                rows[sid][0].add_css_class("done")
                rows[sid][1].set_visible_child_name("done")
            ring.set_fraction(1.0)
            percent.set_label("100%")

    def show(fraction):
        ring.set_fraction(fraction)
        percent.set_label(f"{round(fraction * 100)}%")

    def on_stage(payload):
        stage = payload.get("stage")
        if stage not in rows:
            return
        if state["phase"] != "running":
            set_phase("running")
        state["stage"] = stage
        mark(stage)
        subtitle.set_label(dict((s[0], _(s[1])) for s in STEPS)[stage] + "…")
        show(overall(stage, 0, 0, c.mode()))

    def on_progress(payload):
        stage = state["stage"]
        if stage is None:
            return
        done, total = payload.get("done") or 0, payload.get("total") or 0
        show(overall(stage, done, total, c.mode()))
        if total > 0:
            subtitle.set_label(_("Downloading… {done} of {total}", done=_gib(done), total=_gib(total)))

    def on_play_state(payload):
        if payload.get("state") == "idle" and state["phase"] == "running":
            set_phase("idle")            # it ended without finishing: an error dialog explains why

    def on_done(_payload):
        set_phase("done")
        state["stage"] = None

    def on_action(_btn):
        if state["phase"] == "done":
            win.show_page("play")
            set_phase("idle")
        else:
            c.install(win.toast)

    action.connect("clicked", on_action)
    win.on("setup-stage", on_stage, owner="setup")
    win.on("progress", on_progress, owner="setup")
    win.on("play-state", on_play_state, owner="setup")
    win.on("setup-done", on_done, owner="setup")

    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, halign=Gtk.Align.CENTER,
                  valign=Gtk.Align.CENTER, margin_top=24, margin_bottom=24, margin_start=16, margin_end=16)
    for w in (overlay, title, subtitle, steps_box, action):
        col.append(w)
    set_phase("idle")
    if c.state == "preparing":
        # Rebuilt while an install is running (a language change, say): do not offer
        # "Install now" again, show that it is under way until the next stage arrives.
        set_phase("running")
        subtitle.set_label(getattr(win, "play_message", "") or _("Working…"))
    fade_in(col, 400)
    clamp = Adw.Clamp(maximum_size=460, child=col, vexpand=True)
    return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp)
