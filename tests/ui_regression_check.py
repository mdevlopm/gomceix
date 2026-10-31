"""Headless regression checks for UI/controller-layer bugs (real controller + fake backend).

Run by tests/test_ui_headless.py (pytest does not collect this file itself), or by hand:
      dbus-run-session -- mutter --headless --wayland --no-x11 --virtual-monitor 1200x900 -- \
        env PYTHONPATH=<repo> GTK_A11Y=none GSK_RENDERER=cairo python3 ui_regression_check.py
Prints one PASS/FAIL line per check and a final RESULT line; exit code 1 on failure.
Uses a throw-away XDG_* so the real data folder is never touched.
"""
import os
import sys
import tempfile

_H = tempfile.mkdtemp(prefix="gx-reg-")
os.environ.update(HOME=_H, XDG_DATA_HOME=_H + "/d", XDG_CONFIG_HOME=_H + "/c")

import types  # noqa: E402

if "pytest" not in sys.modules:          # the system python has no pytest; the fake backend only needs the decorator
    _stub = types.ModuleType("pytest")
    _stub.mark = types.SimpleNamespace(parametrize=lambda *a, **k: (lambda f: f))
    sys.modules["pytest"] = _stub

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from gomceix.controller.real import LauncherController  # noqa: E402
from gomceix.core import supervision  # noqa: E402
from gomceix.ui import window as window_module  # noqa: E402
from gomceix.ui.app import Application  # noqa: E402
from tests.test_controller_real import FakeBackend  # noqa: E402

RESULTS = []
SHUTDOWN = []
FALLBACK = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def labels(widget):
    out = []
    for w in walk(widget):
        if isinstance(w, Gtk.Label):
            out.append(w.get_label())
        elif isinstance(w, Gtk.Button) and w.get_label():
            out.append(w.get_label())
        elif isinstance(w, Adw.PreferencesRow):
            out.append(w.get_title())
            if isinstance(w, Adw.ActionRow):
                out.append(w.get_subtitle() or "")
    return out


def pump(ms=120):
    """Let queued GLib callbacks (controller events hop through idle_add) run."""
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def page(win, pid):
    return win.stack.get_child_by_name(pid)


def scenario(app, win, backend, controller):
    c = controller

    # --- Library follows a finished install (setup-done must lead to builds-changed)
    check("library starts empty", any("No versions installed" in t for t in labels(page(win, "library"))),
          str(labels(page(win, "library"))))
    backend.builds = [{"version": "1.21.50.4", "size": 5 * 1024 * 1024, "in_use": True, "edition": "release",
                       "path": "/g/release/1.21.50.4"}]
    c._emit("builds-changed")
    pump()
    check("library lists a build after builds-changed", any("Minecraft 1.21.50" in t for t in labels(page(win, "library"))))

    # --- Library menu button is named (icon-only button)
    menus = [w for w in walk(page(win, "library")) if isinstance(w, Gtk.MenuButton)]
    check("library menu button has a tooltip", bool(menus) and bool(menus[0].get_tooltip_text()))

    # --- Play page follows sign-in changes
    check("play says not signed in", any("Not signed in" in t for t in labels(page(win, "play"))),
          str(labels(page(win, "play"))))
    backend.msa = True
    c._emit("accounts-changed")
    pump()
    check("play shows the gamertag after accounts-changed", any("Steve" in t for t in labels(page(win, "play"))))

    # --- Play page survives a selection that is not in the list (catalogue replaced between two reads)
    real_selected = c.selected_version
    c.selected_version = lambda: "no-such-version"
    try:
        win.refresh_page("play")
        pump()
        check("play builds when the selection is not in the list", True)
    except Exception as exc:
        check("play builds when the selection is not in the list", False, repr(exc))
    c.selected_version = real_selected
    win.refresh_page("play")

    # --- Narrow window: awkward data must not push the window wider than its 360 px minimum
    original_display = backend.display_version
    original_name = backend.msa_gamertag
    backend.display_version = lambda tag, beta: "26.100.123.7-preview"
    backend.msa_gamertag = lambda: "ÇokUzunBirOyuncuAdı1234567"
    backend.gpus = [("0000:01:00.0", "NVIDIA GeForce RTX 4070 SUPER Laptop GPU Ada Generation (0000:01:00.0) — runs the display")]
    c.refresh_catalog()
    pump()
    win.refresh_page("play")
    win.refresh_page("settings")
    for pid in ("play", "settings", "library", "saves", "accounts", "requirements"):
        width = page(win, pid).measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        check(f"{pid} page fits a 360 px window with long names", width <= 360, str(width))
    backend.display_version, backend.msa_gamertag, backend.gpus = original_display, original_name, []
    c.refresh_catalog()
    pump()

    # --- Welcome version list fills when the catalogue arrives and drives the install
    welcome = page(win, "welcome")
    combo = next(w for w in walk(welcome) if isinstance(w, Adw.ComboRow))
    check("welcome combo lists versions", combo.get_model().get_n_items() == 2, str(combo.get_model().get_n_items()))
    combo.set_selected(1)
    check("welcome choice is the one that is installed", c.selected_version() == "1.21.40", c.selected_version())
    backend.versions["release"].append({"version": "1.21.30.1", "installed": False})
    c.refresh_catalog()
    pump()
    check("welcome keeps the saved selection when the list refills", c.selected_version() == "1.21.40", c.selected_version())
    welcome = page(win, "welcome")      # (not rebuilt: handler fills in place)
    combo = next(w for w in walk(welcome) if isinstance(w, Adw.ComboRow))
    check("welcome combo shows the selection", combo.get_selected() == 1 and combo.get_model().get_n_items() == 3)

    # --- Settings survive hand-edited garbage in settings.json
    backend.settings.update(renderer=None, gpu=0)
    try:
        win.refresh_page("settings")
        pump()
        rows = [w for w in walk(page(win, "settings")) if isinstance(w, Adw.ComboRow)]
        check("settings page builds with null/number choices", len(rows) >= 4)
    except Exception as exc:
        check("settings page builds with null/number choices", False, repr(exc))

    # --- Close-on-launch switch is shared by Play and Settings
    play_sw = next(w for w in walk(page(win, "play")) if isinstance(w, Gtk.Switch))
    c.set_setting("close_on_launch", True)
    pump()
    play_sw = next(w for w in walk(page(win, "play")) if isinstance(w, Gtk.Switch))
    check("play switch follows the Settings page", play_sw.get_active())
    play_sw.set_active(False)
    pump()
    settings_rows = [w for w in walk(page(win, "settings")) if isinstance(w, Adw.SwitchRow)
                     and w.get_title().startswith("Close the launcher")]
    check("settings switch follows the Play page", bool(settings_rows) and not settings_rows[0].get_active())

    # --- A page whose rebuild fails keeps its event handlers
    backend.store = False                  # a signed-out Store row registers a store-login handler
    win.refresh_page("accounts")
    before = len(win._handlers.get("accounts", []))
    original = window_module.PAGES
    broken = [(p, t, i, (lambda w: 1 / 0) if p == "accounts" else b) for p, t, i, b in original]
    window_module.PAGES = broken
    win.refresh_page("accounts")
    window_module.PAGES = original
    check("failed rebuild keeps handlers", len(win._handlers.get("accounts", [])) == before and before > 0,
          f"{before} -> {len(win._handlers.get('accounts', []))}")

    # --- the Microsoft / ProxyPass sign-in code dialog: every button does what it says
    clipboard = win.get_clipboard()

    def clipboard_text():
        box, done = {}, []
        clipboard.read_text_async(None, lambda cb, res: (box.update(text=cb.read_text_finish(res)), done.append(1)))
        for _ in range(30):
            if done:
                break
            pump(50)
        return box.get("text")

    def find_button(dialog, label):
        return next((w for w in walk(dialog.get_extra_child()) if isinstance(w, Gtk.Button) and w.get_label() == label), None)

    opened, cancelled = [], []
    real_launcher = window_module.Gtk.UriLauncher

    class FakeLauncher:
        def __init__(self, uri): self.uri = uri
        @classmethod
        def new(cls, uri): return cls(uri)
        def launch(self, parent, cancellable, callback): opened.append(self.uri)

    window_module.Gtk.UriLauncher = FakeLauncher
    original_cancel = c.cancel_microsoft_login
    c.cancel_microsoft_login = lambda: cancelled.append(1)
    clipboard.set("something else")
    win._on_event("ms-code", {"url": "https://www.microsoft.com/link", "code": "59EW7MQL"})
    pump()
    dialog = win._ms_dialog
    check("code dialog opens on the ms-code event", dialog is not None)
    check("the code is copied to the clipboard by itself", clipboard_text() == "59EW7MQL", str(clipboard_text()))
    clipboard.set("overwritten")
    copy_btn, open_btn = find_button(dialog, "Copy code"), find_button(dialog, "Open sign-in page")
    check("code dialog has a Copy and an Open button", copy_btn is not None and open_btn is not None)
    copy_btn.emit("clicked")
    pump()
    check("Copy code puts the code back on the clipboard", clipboard_text() == "59EW7MQL", str(clipboard_text()))
    open_btn.emit("clicked")
    check("Open sign-in page opens the sign-in address", opened == ["https://www.microsoft.com/link"], str(opened))
    check("the code is shown selectable", any(isinstance(w, Gtk.Label) and w.get_label() == "59EW7MQL" and w.get_selectable()
                                               for w in walk(dialog.get_extra_child())))
    win._on_event("ms-code", {"url": "https://www.microsoft.com/link", "code": "NEWCODE12"})
    pump()
    check("a newer code replaces the dialog, it does not stack", win._ms_dialog is not dialog and clipboard_text() == "NEWCODE12")
    win._ms_dialog.close()
    pump()
    check("closing the dialog cancels the sign-in once", cancelled == [1], str(cancelled))
    win._on_event("ms-code", {"url": "https://www.microsoft.com/link", "code": "ZZZZ9999"})
    pump()
    win._on_event("ms-code-done", {"linked": True})
    pump()
    check("finishing the sign-in closes the dialog without cancelling it", win._ms_dialog is None and cancelled == [1], str(cancelled))
    window_module.Gtk.UriLauncher = real_launcher
    c.cancel_microsoft_login = original_cancel

    # --- Settings > ProxyPass: the server row lists the Hive and picking it writes its address
    win.refresh_page("settings")
    pump()
    rows = [w for w in walk(page(win, "settings")) if isinstance(w, Adw.ComboRow) and w.get_title() == "Server"]
    check("settings has a Server row", len(rows) == 1)
    if rows:
        model = rows[0].get_model()
        items = [model.get_string(i) for i in range(model.get_n_items())]
        check("the Server row offers Hive and a custom address", items == ["Hive", "Custom address"], str(items))
        backend.dest = ("play.example.net", "25565")
        rows[0].set_selected(0)
        pump()
        check("picking Hive writes the Hive's address", backend.dest == ("geo.hivebedrock.network", "19132"), str(backend.dest))

    # --- Settings > ProxyPass: the online mode switch decides whether a ProxyPass sign-in exists
    mode_before = c.mode()
    c.set_mode("proxypass")
    pump()
    win.refresh_page("settings")
    pump()
    rows = [w for w in walk(page(win, "settings")) if isinstance(w, Adw.SwitchRow) and w.get_title() == "Online mode"]
    check("settings has an Online mode switch, on by default", len(rows) == 1 and rows[0].get_active())
    if rows:
        win.refresh_page("accounts")
        pump()
        check("online mode on lists the ProxyPass sign-in", "ProxyPass account (play online)" in labels(page(win, "accounts")))
        rows[0].set_active(False)
        pump()
        check("the switch writes online mode off", backend.proxy_online is False)
        check("online mode off hides the ProxyPass sign-in", "ProxyPass account (play online)" not in labels(page(win, "accounts")))
        check("online mode off asks for no ProxyPass sign-in", c.needs_proxy_login() is False)
        c.set_setting("proxypass_online", True)
        pump()
    c.set_mode(mode_before)
    pump()

    # --- several errors in a row are shown one after another, not stacked
    shown = []
    win._present_alert = lambda h, b, a: shown.append(h)       # record instead of drawing
    win._alert_open = False
    win.alert("first", "a")
    win.alert("second", "b")
    win.alert("second", "b")                                    # an identical one is not queued twice
    check("alerts: only the first is shown at once", shown == ["first"], str(shown))
    win._alert_closed(None)
    check("alerts: the next one follows when it is closed", shown == ["first", "second"], str(shown))
    win._alert_closed(None)
    check("alerts: the queue empties", win._alert_open is False and not win._alert_queue)
    del win._present_alert

    # --- Accounts page rebuilt while a Store window is open still offers Cancel
    import threading
    gate = threading.Event()
    backend.store_login = lambda: gate.wait(5)
    backend.LoginCancelled = type("LC", (Exception,), {})
    c.sign_in_store()
    pump()
    win.refresh_page("accounts")
    pump()
    check("accounts shows Cancel for an open Store window", "Cancel" in labels(page(win, "accounts")))
    gate.set()
    pump(300)

    # --- Setup page rebuilt mid-install does not offer "Install now" again
    # The gate above returns without signing in; a real login raises then. Left in place it would
    # make PLAY ask for the sign-in again and again, so go back to the fake's signed-in Store.
    del backend.store_login
    backend.store = True                   # signed in to the Store: PLAY starts instead of asking for the sign-in
    backend.hold_launch = True
    c.play()
    for _i in range(100):
        pump(20)
        if c.state == "running":
            break
    check("play reaches the running state", c.state == "running", c.state)
    win.refresh_page("setup")
    c.stop()
    for _i in range(100):
        pump(20)
        if c.state == "idle":
            break
    check("play returned to idle", c.state == "idle")
    # preparing state: emulate directly (the fake backend's setup is instantaneous)
    c._state = "preparing"
    win.refresh_page("setup")
    visible = [w for w in walk(page(win, "setup")) if isinstance(w, Gtk.Button) and w.get_visible()]
    check("setup rebuilt while preparing hides the action button", not visible, str([b.get_label() for b in visible]))
    c._state = "idle"

    # --- a stop signal (poweroff, stopped scope) waits for the session's teardown
    import signal
    import threading
    import time
    redelivered = []
    real_redeliver = supervision._redeliver
    supervision._redeliver = redelivered.append
    supervision.begin_session()
    threading.Timer(0.4, supervision.end_session).start()
    started = time.monotonic()
    os.kill(os.getpid(), signal.SIGTERM)
    pump(900)
    check("SIGTERM during a session is held until its teardown is done",
          redelivered == [signal.SIGTERM] and time.monotonic() - started >= 0.35, str(redelivered))
    supervision._redeliver = real_redeliver
    supervision._state.update(active=False, signum=None, since=None)

    # --- closing the window while the game runs hides it; the process stays until the session ends
    app.connect("shutdown", lambda _app: SHUTDOWN.append(1))
    c._state = "running"
    for _i in range(3):                    # libadwaita answers a close with an open dialog by closing that dialog first
        win.close()
        pump(50)
        if win._session_hold:
            break
    check("closing the window while the game runs only hides it",
          win._session_hold and not win.get_visible() and win in app.get_windows(),
          f"{win._session_hold} {win.get_visible()}")
    c._set_state("idle")
    pump()
    check("the window is gone once the session has ended", not win._session_hold and win not in app.get_windows())
    GLib.timeout_add(1500, lambda: FALLBACK.append(1) or app.quit())   # only if the launcher stays up by itself
    return False


def main():
    backend = FakeBackend()
    controller = LauncherController(backend)
    controller.refresh_catalog()

    def on_window(win):
        shown = win.stack.get_child_by_name("library")
        check("a page that fails to build becomes a status page, the app still opens",
              isinstance(shown, Adw.StatusPage), type(shown).__name__)
        window_module.PAGES = ORIGINAL
        win.refresh_page("library")
        GLib.timeout_add(300, scenario, app, win, backend, controller)

    ORIGINAL = window_module.PAGES
    window_module.PAGES = [(p, t, i, (lambda w: 1 / 0) if p == "library" else b) for p, t, i, b in ORIGINAL]
    app = Application(controller=controller, on_window=lambda w: GLib.timeout_add(300, on_window, w) and None)
    app.run([])
    check("the launcher ends by itself when the last session ends", bool(SHUTDOWN) and not FALLBACK)
    print("RESULT", "ok" if all(RESULTS) else "FAILED", f"{sum(RESULTS)}/{len(RESULTS)}", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
