"""Requirements: what Gomceix downloads for itself, plus health checks and upkeep.

Every component is stored in Gomceix's own folder, so installing or removing
one affects nothing else on the system.
"""
from __future__ import annotations

from gi.repository import Adw, Gtk

from gomceix.i18n import _, N_

from ..widgets import button, row

TITLE, ICON = N_("Requirements"), "package-x-generic-symbolic"

_STATUS_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "warn": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
}


def _status_icon(status: str) -> Gtk.Image:
    icon_name, style_class = _STATUS_ICONS.get(status, ("dialog-error-symbolic", "error"))
    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.add_css_class(style_class)
    return icon


def human_size(n) -> str:
    if n is None:
        return "…"
    if n < 1024 * 1024:
        return f"{max(n, 1) // 1024 or 1} KB" if n else "0 KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.0f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _confirm(win, heading: str, body: str, response: str, label: str, action) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.set_heading_use_markup(False)
    dialog.set_body_use_markup(False)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response(response, label)
    dialog.set_response_appearance(response, Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, answer: action() if answer == response else None)
    dialog.present(win)


def _maintenance_row(title: str, on_activate) -> Adw.ActionRow:
    action = row(title)
    action.set_activatable(True)
    action.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    action.connect("activated", lambda _row: on_activate())
    return action


def _subtitle(info, mode: str) -> str:
    parts = [info.description]
    if info.busy:
        parts.append(_("Working…"))
    elif info.installed or info.kind == "cache":
        parts.append(human_size(info.size_bytes))
    if info.needed_for == "proxypass" and mode != "proxypass":
        parts.append(_("ProxyPass mode only"))
    return "  ·  ".join(parts)


def _component_row(win, info, mode: str, live: dict):
    r = row(info.title, _subtitle(info, mode))
    if info.kind == "cache":
        r.add_prefix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
    elif info.busy:
        r.add_prefix(Gtk.Spinner(spinning=True))
    else:
        r.add_prefix(_status_icon("ok") if info.installed else _status_icon("warn"))
    live[info.id] = r
    c = win.controller
    if info.busy:
        return r
    if info.kind == "cache":
        clear = button(_("Clear"), "secondary", small=True)
        clear.set_sensitive(bool(info.size_bytes))
        clear.connect("clicked", lambda *_a: c.remove_requirement(info.id))
        r.add_suffix(clear)
    elif info.installed and info.removable:
        remove = button(_("Remove"), "secondary", small=True)
        remove.connect("clicked", lambda *_a: _confirm(
            win, _("Remove {name}?", name=info.title),
            _("It is deleted from Gomceix's own folder only. You can download it again at any time."),
            "remove", _("Remove"), lambda: c.remove_requirement(info.id)))
        r.add_suffix(remove)
    elif info.installed:
        chip = Gtk.Label(label=_("Provided by your system"))
        chip.add_css_class("dim-label")
        r.add_suffix(chip)
    else:
        get = button(_("Download"), "primary", small=True)
        get.connect("clicked", lambda *_a: c.install_requirement(info.id))
        r.add_suffix(get)
    return r


def build(win):
    c = win.controller
    mode = c.mode()
    items = c.requirements()
    components = [i for i in items if i.kind == "component"]
    cache = [i for i in items if i.kind == "cache"]
    live: dict = {}
    page = Adw.PreferencesPage()

    present = [i for i in components if i.installed]
    measured = [i.size_bytes for i in present if i.size_bytes is not None]
    total = human_size(sum(measured)) if len(measured) == len(present) else "…"
    group = Adw.PreferencesGroup(
        title=_("Components"),
        description=_("{have} of {all} installed  ·  {size} on disk. Everything is kept in Gomceix's own folder and nothing is installed system-wide.",
                     have=len(present), all=len(components), size=total))
    wanted = [i for i in components if not i.installed and i.removable
              and (i.needed_for == "all" or mode == "proxypass")]
    queue = getattr(win, "_requirement_queue", [])
    if wanted and not queue and not any(i.busy for i in components):
        get_all = button(_("Download missing"), "primary", small=True)

        def start_all(*_a):
            win._requirement_queue = [i.id for i in wanted][1:]
            c.install_requirement(wanted[0].id)

        get_all.connect("clicked", start_all)
        group.set_header_suffix(get_all)
    for info in components:
        group.add(_component_row(win, info, mode, live))
    page.add(group)

    if cache:
        space = Adw.PreferencesGroup(title=_("Space"))
        space.add(_component_row(win, cache[0], mode, live))
        page.add(space)

    # --- health checks of the whole setup
    checks = c.diagnostics()
    health = Adw.PreferencesGroup(title=_("Health"))
    check_again = button(_("Check again"), "secondary", small=True)
    check_again.connect("clicked", lambda *_a: (c.refresh_requirement_sizes(), win.refresh_page("requirements")))
    health.set_header_suffix(check_again)
    for check in checks:
        result = row(check.title, check.detail)
        result.set_activatable(False)
        result.add_prefix(_status_icon(check.status))
        health.add(result)
    if checks and all(check.status == "ok" for check in checks):
        good = row(_("Everything looks good"))
        good.set_activatable(False)
        good.add_prefix(_status_icon("ok"))
        health.add(good)
    page.add(health)

    maintenance = Adw.PreferencesGroup(title=_("Maintenance"))
    maintenance.add(_maintenance_row(_("Open logs folder"), c.open_logs))
    maintenance.add(_maintenance_row(
        _("Repair (reset the Wine prefix)"),
        lambda: _confirm(win, _("Repair the Wine prefix?"),
                         _("Repair keeps your worlds and settings, but it stops a running game."),
                         "repair", _("Repair"), c.repair)))
    maintenance.add(_maintenance_row(
        _("Force stop Minecraft"),
        lambda: _confirm(win, _("Force stop Minecraft?"),
                         _("Force stop closes the game immediately. Unsaved progress will be lost."),
                         "force-stop", _("Force stop"), c.force_stop)))
    page.add(maintenance)

    def on_progress(payload):
        target = live.get(payload.get("id"))
        done, total_bytes = payload.get("done") or 0, payload.get("total") or 0
        if target is not None and total_bytes > 0:
            by_id = {i.id: i for i in items}
            target.set_subtitle(f"{by_id[payload['id']].description}  ·  "
                                + _("Downloading… {done} of {total}", done=human_size(done), total=human_size(total_bytes)))

    def on_component_done(payload):
        if payload.get("state") == "refused":
            win._requirement_queue = []        # the controller said no (a game is running): stop the queue, do not hang it
            win.refresh_page("requirements")   # and bring "Download missing" back
            return
        if payload.get("state") != "done":
            return
        queue = getattr(win, "_requirement_queue", [])
        if queue:
            nxt, win._requirement_queue = queue[0], queue[1:]
            c.install_requirement(nxt)

    win.on("component-progress", on_progress, owner="requirements")
    win.on("component", on_component_done, owner="requirements")
    return page
