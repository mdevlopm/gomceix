"""Main window: sidebar navigation + pages. Plain Python on GTK4/libadwaita."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from gomceix import APP_NAME  # noqa: E402
from gomceix.controller import Controller  # noqa: E402

from . import pages  # noqa: E402
from .theme import ThemeManager  # noqa: E402
from .widgets import button  # noqa: E402
from gomceix.i18n import _

PAGES = pages.load()  # [(id, title, icon, build)]

# Controller states with a game process that this process still has to tidy up after.
SESSION_STATES = ("running", "stopping")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, controller: Controller, themes: ThemeManager, user_prefs: dict):
        super().__init__(application=app, title=APP_NAME, default_width=1040, default_height=700)
        self.controller, self.themes, self.prefs = controller, themes, user_prefs
        self.set_size_request(360, 400)

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=210, max_sidebar_width=260)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        self._handlers: dict[str, list] = {}   # owner page id -> [(event, callback)]
        self._stepped_aside = False
        self._session_hold = False             # the application is held for a game that outlives the window
        self.connect("close-request", self._on_close_request)
        self.play_message = ""
        self._nav_rows: list = []
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=260)
        self._build_sidebar()
        self._build_content()
        self.show_page("play")
        self._connect_controller()
        if getattr(self.controller, "needs_welcome", lambda: False)():
            self.show_page("welcome")      # a new user starts with the guide

    # ------------------------------------------------------------ structure
    def _build_sidebar(self):
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        self._window_title = Adw.WindowTitle(title=APP_NAME, subtitle=_("Bedrock launcher for GNOME"))
        header.set_title_widget(self._window_title)
        view.add_top_bar(header)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        for pid, title, icon, _b in PAGES:
            if pid in pages.HIDDEN:
                continue
            row = Adw.ActionRow(title=_(title), use_markup=False)  # titles may contain "&"
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.page_id = pid
            self._nav_rows.append((row, title))
            self.nav.append(row)
        self.nav.connect("row-selected", self._on_nav)
        view.set_content(self.nav)
        self.split.set_sidebar(Adw.NavigationPage(title=APP_NAME, child=view))

    def _build_content(self):
        self.content_view = Adw.ToolbarView()
        top = Adw.HeaderBar()
        top.add_css_class("flat")
        self.content_view.add_top_bar(top)
        self.content_view.set_content(self.stack)
        self.content_page = Adw.NavigationPage(title=_("Play"), child=self.content_view)
        self.split.set_content(self.content_page)
        for pid, _title, _icon, build in PAGES:
            self.stack.add_named(self._build_page(pid, build), pid)

    def _build_page(self, pid: str, build) -> Gtk.Widget:
        """One page, or a plain explanation when it cannot be built: a page that
        fails on bad data (an unreadable folder, a hand-edited settings file) must
        not stop the whole launcher from opening."""
        try:
            return build(self)
        except Exception as exc:
            print(f"[ui] page {pid!r} could not be built: {exc!r}")
            self.clear_handlers(pid)
            return Adw.StatusPage(icon_name="dialog-error-symbolic", title=_("This page could not be shown"),
                                  description=_("Something went wrong while loading it. Details: {error}",
                                                error=str(exc) or type(exc).__name__))

    def _on_nav(self, _box, row):
        if row is not None:
            self.show_page(row.page_id, from_nav=True)

    def show_page(self, pid: str, from_nav: bool = False):
        title = next(t for p, t, _i, _b in PAGES if p == pid)
        if self.stack.get_child_by_name(pid) is None:
            return
        self.stack.set_visible_child_name(pid)
        self.content_page.set_title(_(title))
        if not from_nav:
            visible = [p for p, *_rest in PAGES if p not in pages.HIDDEN]
            if pid in visible:
                self.nav.select_row(self.nav.get_row_at_index(visible.index(pid)))
            else:
                self.nav.unselect_all()
        if from_nav:
            self.split.set_show_content(True)

    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=text, use_markup=False, timeout=3))

    # --------------------------------------------------------------- events
    def _on_close_request(self, _win):
        """The game's teardown (GPU marker, frame limit, logs, presence) runs on a
        thread of this process, and ProxyPass stops with it. While a session
        runs, closing the window (the X button or the close-on-launch setting)
        hides it and keeps the process until the session has ended."""
        if self.controller.state not in SESSION_STATES:
            return False
        if not self._session_hold:
            self._session_hold = True
            self.get_application().hold()
        self.set_visible(False)
        return True

    def _end_session_hold(self):
        if not self._session_hold:
            return
        self._session_hold = False
        app = self.get_application()
        if not self.get_visible():
            self.destroy()                      # it was closed, not brought back
        app.release()

    def _connect_controller(self):
        """Controller events arrive on any thread; hop to the GTK main loop."""
        connect = getattr(self.controller, "connect", None)
        if connect:
            connect(lambda name, payload: GLib.idle_add(self._deliver, name, payload))
        start = getattr(self.controller, "start", None)
        if start:
            start()
        measure = getattr(self.controller, "refresh_requirement_sizes", None)
        if measure:
            measure()

    def on(self, event: str, callback, owner: str = ""):
        """Register `callback(payload)` for a controller event (main thread).
        `owner` is the page id: its handlers are dropped when the page is rebuilt."""
        self._handlers.setdefault(owner, []).append((event, callback))

    def clear_handlers(self, owner: str):
        self._handlers.pop(owner, None)

    def _deliver(self, name: str, payload: dict):
        if name == "play-state":
            self.play_message = payload.get("message", "")      # a rebuilt Play page shows it again
        for handlers in list(self._handlers.values()):
            for event, callback in list(handlers):
                if event == name:
                    try:
                        callback(payload)
                    except Exception as exc:  # a page bug must not stop the others
                        print(f"[ui] handler for {name!r} failed: {exc}")
        self._on_event(name, payload)
        return False  # GLib.idle_add: run once

    def _on_event(self, name: str, payload: dict):
        if name == "error":
            self.alert(payload.get("title", _("Something went wrong")), payload.get("message", ""))
        elif name == "needs-store-signin":
            self.alert(_("Sign in to download the game"), payload.get("message", ""),
                       action=(_("Open Accounts"), lambda: self.show_page("accounts")))
        elif name == "game-problem":
            self.toast(payload.get("message", _("Minecraft did not end normally.")))
        elif name == "notice":
            self.alert(_("Minecraft"), payload.get("text", ""))
        elif name == "game-started":
            action = payload.get("window_action")
            if action == "close":
                self.close()
            elif action == "step-aside":
                self._stepped_aside = True
                self.minimize()
        elif name == "game-closed" and self._stepped_aside:
            self._stepped_aside = False
            self.present()
        elif name == "catalog-changed":
            self.refresh_page("play")
            self.refresh_page("library")
        elif name == "store-login":
            state = payload.get("state")
            if state == "done":
                self.toast(_("Store account linked."))
            elif state == "cancelled":
                self.toast(_("Store sign-in cancelled."))
        elif name == "ms-code":
            self._show_ms_code(payload.get("url", ""), payload.get("code", ""))
        elif name == "ms-code-done":
            self._close_ms_code()
            if payload.get("linked"):
                self.toast(_("Microsoft account linked."))
        elif name == "maintenance":
            if payload.get("state") == "done":
                self.toast(_("Repair finished.") if payload.get("job") == "repair" else _("Minecraft was stopped."))
            elif payload.get("state") == "running":
                self.toast(_("Repairing… this can take a minute."))
        elif name == "builds-changed":
            for pid in ("library", "play", "requirements"):
                self.refresh_page(pid)
        elif name == "play-state":
            self.refresh_page("library")          # "in use" (and so Remove) follows the game's state
            if payload.get("state") == "idle":
                self._end_session_hold()
        elif name in ("requirements-changed", "requirements-sizes", "component"):
            if name != "component" or payload.get("state") == "running":
                self.refresh_page("requirements")
        elif name == "open-setup":
            self.show_page("setup")
        elif name == "toast":
            self.toast(payload.get("text", ""))
        elif name == "proxy-destination-changed":
            for pid in ("play", "settings"):
                self.refresh_page(pid)
        elif name == "setting-rejected":
            for pid in ("play", "settings"):             # both show saved choices
                self.refresh_page(pid)
        elif name == "mode-changed":
            for pid in ("play", "accounts", "requirements"):
                self.refresh_page(pid)
        elif name == "accounts-changed":
            for pid in ("play", "accounts", "requirements"):     # Play shows who is signed in
                self.refresh_page(pid)

    def refresh_page(self, pid: str):
        """Rebuild one page from fresh controller data, keeping it on screen."""
        build = next((b for p, _t, _i, b in PAGES if p == pid), None)
        old = self.stack.get_child_by_name(pid)
        if build is None or old is None:
            return
        was_visible = self.stack.get_visible_child_name() == pid
        old_handlers = self._handlers.pop(pid, None)
        try:
            fresh = build(self)
        except Exception as exc:
            # A page that fails to build must never take its old self, or the
            # navigation, down with it: keep what was on screen, and keep it
            # alive (its event handlers come back; the half-built page's go).
            print(f"[ui] page {pid!r} could not be rebuilt: {exc!r}")
            self.clear_handlers(pid)
            if old_handlers is not None:
                self._handlers[pid] = old_handlers
            return
        self.stack.remove(old)
        self.stack.add_named(fresh, pid)
        if was_visible:
            self.stack.set_visible_child_name(pid)

    def alert(self, heading: str, body: str, action=None):
        """A plain dialog: heading, wrapped body, optional extra button. Several
        in a row are shown one after another, not stacked on top of each other."""
        queue = self.__dict__.setdefault("_alert_queue", [])
        if getattr(self, "_alert_open", False):
            if (heading, body) not in [(h, b) for h, b, _a in queue]:
                queue.append((heading, body, action))
            return
        self._alert_open = True
        self._present_alert(heading, body, action)

    def _present_alert(self, heading: str, body: str, action):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.connect("closed", self._alert_closed)
        dialog.set_heading_use_markup(False)
        dialog.set_body_use_markup(False)
        dialog.add_response("close", _("Close"))
        dialog.set_close_response("close")
        if action:
            label, callback = action
            dialog.add_response("action", label)
            dialog.set_response_appearance("action", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", lambda _d, r: callback() if r == "action" else None)
        dialog.present(self)

    def _alert_closed(self, _dialog):
        queue = self.__dict__.setdefault("_alert_queue", [])
        if queue:
            self._present_alert(*queue.pop(0))
        else:
            self._alert_open = False

    # ----------------------------------------------- Microsoft device-code dialog
    def _show_ms_code(self, url: str, code: str):
        self._close_ms_code()
        dialog = Adw.AlertDialog(
            heading=_("Sign in to Microsoft"),
            body=_("Open the page below, then enter this code. Gomceix finishes on its own once you have signed in."))
        dialog.set_heading_use_markup(False)
        dialog.set_body_use_markup(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=6)
        code_label = Gtk.Label(label=code, selectable=True)
        code_label.add_css_class("title-1")
        code_label.add_css_class("monospace")
        box.append(code_label)
        copy = button(_("Copy code"), "secondary", halign=Gtk.Align.CENTER)
        copy.connect("clicked", lambda *_args: (self.get_clipboard().set(code), self.toast(_("Code copied."))))
        open_btn = button(_("Open sign-in page"), "primary", halign=Gtk.Align.CENTER)
        open_btn.connect("clicked", lambda *_args: Gtk.UriLauncher.new(url).launch(self, None, None))
        box.append(open_btn)
        box.append(copy)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", _("Cancel"))
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, _r: self._ms_dialog_closed(dialog))
        self._ms_dialog = dialog
        self.get_clipboard().set(code)            # ready to paste on the sign-in page
        self.toast(_("Code copied."))
        dialog.present(self)

    def _ms_dialog_closed(self, dialog):
        if getattr(self, "_ms_dialog", None) is dialog:
            self._ms_dialog = None
            self.controller.cancel_microsoft_login()   # idempotent if it already finished

    def _close_ms_code(self):
        dialog, self._ms_dialog = getattr(self, "_ms_dialog", None), None
        if dialog is not None:
            dialog.force_close()

    def retranslate(self):
        """Re-draw everything in the language that was just selected: sidebar,
        header, and every page rebuilt from the controller. The Settings page
        is rebuilt on the next idle, because the row that triggered this lives in it."""
        self._window_title.set_subtitle(_("Bedrock launcher for GNOME"))
        for row, title in self._nav_rows:
            row.set_title(_(title))
        current = self.stack.get_visible_child_name() or "play"
        self.content_page.set_title(_(next(t for p, t, _i, _b in PAGES if p == current)))
        for pid, *_rest in PAGES:
            if pid != "settings":
                self.refresh_page(pid)
        GLib.idle_add(lambda: (self.refresh_page("settings"), False)[1])
