"""Application entry point."""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib  # noqa: E402

from gomceix import i18n  # noqa: E402
from gomceix.controller import DemoController  # noqa: E402
from gomceix.core import supervision  # noqa: E402

from . import prefs  # noqa: E402
from .theme import ThemeManager  # noqa: E402
from .window import MainWindow  # noqa: E402

APP_ID = "io.github.mdevlopm.Gomceix"   # must equal the desktop file and Flatpak id


def default_controller():
    """The real controller, unless GOMCEIX_DEMO=1 asks for static demo data
    (used by the screenshot tool and for trying the UI without a game)."""
    if os.environ.get("GOMCEIX_DEMO") == "1":
        return DemoController()
    from gomceix.controller.real import LauncherController
    return LauncherController()


class Application(Adw.Application):
    def __init__(self, controller=None, on_window=None):
        super().__init__(application_id=APP_ID)
        self.controller = controller or default_controller()
        self.on_window = on_window
        self.themes = ThemeManager()

    def do_startup(self):
        Adw.Application.do_startup(self)
        # A poweroff or a stopped scope with the game running lets the launch
        # finish its teardown first (GPU marker, frame limit, logs). GLib
        # delivers the signal on the main loop, where waiting is allowed.
        for signum in supervision.default_signals():
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, self._on_stop_signal, signum)

    @staticmethod
    def _on_stop_signal(signum):
        supervision.hold_for_signal(signum)
        return GLib.SOURCE_REMOVE

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            user_prefs = prefs.load()
            i18n.set_language(user_prefs["language"])
            self.themes.apply_prefs(user_prefs)
            win = MainWindow(self, self.controller, self.themes, user_prefs)
        win.present()
        if self.on_window:
            self.on_window(win)


def main(argv=None) -> int:
    return Application().run(argv if argv is not None else sys.argv)
