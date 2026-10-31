"""Controller layer: the only thing the UI talks to. No GTK imports here.

P0 ships a demo controller with static data; the real one (P1) wraps the
backend modules and implements the same methods, so pages never change.
"""
from __future__ import annotations

from typing import Callable, Protocol

from gomceix.i18n import _
from .models import Account, BuildInfo, CheckResult, RequirementInfo, SaveInfo

__all__ = ["Controller", "DemoController", "LauncherController", "Account", "BuildInfo", "CheckResult", "RequirementInfo", "SaveInfo"]


class Controller(Protocol):
    def account_name(self) -> str | None: ...
    def accounts(self) -> list[Account]: ...
    def versions(self) -> list[str]: ...
    def builds(self) -> list[BuildInfo]: ...
    def selected_version(self) -> str: ...
    def set_version(self, version: str) -> None: ...
    def channel(self) -> str: ...
    def saves(self) -> list[SaveInfo]: ...
    def diagnostics(self) -> list[CheckResult]: ...
    def play(self, on_status: Callable[[str], None]) -> None: ...
    def stop(self) -> None: ...
    def set_channel(self, channel: str) -> None: ...
    def catalog_loaded(self) -> bool: ...
    def catalog_failed(self) -> bool: ...
    def reload_catalog(self) -> None: ...
    def use_build(self, tag: str, channel: str) -> None: ...
    def remove_build(self, path: str) -> None: ...
    def sign_in_store(self) -> None: ...
    def store_login_running(self) -> bool: ...
    def cancel_store_login(self) -> None: ...
    def sign_out_store(self) -> None: ...
    def sign_in_microsoft(self) -> None: ...
    def cancel_microsoft_login(self) -> None: ...
    def sign_out_microsoft(self) -> None: ...
    def open_logs(self) -> None: ...
    def repair(self) -> None: ...
    def force_stop(self) -> None: ...
    def refresh_diagnostics(self) -> None: ...
    def needs_welcome(self) -> bool: ...
    def requirements(self) -> list[RequirementInfo]: ...
    def refresh_requirement_sizes(self) -> None: ...
    def install_requirement(self, cid: str) -> None: ...
    def remove_requirement(self, cid: str) -> None: ...
    def needs_store_login(self) -> bool: ...
    def proxy_missing(self) -> list[str]: ...
    def needs_proxy_login(self) -> bool: ...
    def proxy_supported(self) -> list | None: ...
    def proxy_problem(self) -> str | None: ...
    def proxy_skipped(self) -> bool: ...
    def mode(self) -> str: ...
    def set_mode(self, mode: str) -> None: ...
    def proxy_destination(self) -> tuple[str, str]: ...
    def install_needed(self) -> bool: ...
    def install(self, on_status: Callable[[str], None]) -> None: ...
    def settings_groups(self) -> list: ...
    def get_setting(self, key: str): ...
    def set_setting(self, key: str, value) -> None: ...
    def close_on_launch(self) -> bool: ...
    def set_close_on_launch(self, value: bool) -> None: ...
    state: str


class DemoController:
    def __init__(self):
        self._version = "26.52"

    def account_name(self):
        return "Steve"

    def accounts(self):
        if self.mode() == "proxypass":
            return [Account("proxypass", True, _("ProxyPass"), _("Needed to play online in ProxyPass mode")),
                    Account("store", False, None, _("Needed to download the game"))]
        return [Account("microsoft", True, "Steve", _("Needed to play online")),
                Account("store", False, None, _("Needed to download the game"))]

    def versions(self):
        if self.mode() == "proxypass":
            return ["26.30", "26.20", "26.10"]
        return ["26.52", "26.51", "26.50", "26.40"]

    def builds(self):
        return [BuildInfo("26.52", "Stable", 2310, selected=self._version == "26.52", tag="1.26.52.1", path="/demo/games/1.26.52.1"),
                BuildInfo("26.51", "Stable", 2290, selected=self._version == "26.51", tag="1.26.51.1", path="/demo/games/1.26.51.1"),
                BuildInfo("26.50", "Stable", 2280, selected=self._version == "26.50", in_use=True, tag="1.26.50.1", path="/demo/games/1.26.50.1"),
                BuildInfo("26.40-preview", "Preview", 2250, selected=self._version == "26.40", tag="1.26.40.1", path="/demo/games/1.26.40.1")]

    def selected_version(self):
        return self._version

    def set_version(self, version):
        self._version = version

    def channel(self):
        return "Stable"

    def saves(self):
        return [SaveInfo("My Survival World", 412, "Yesterday"),
                SaveInfo("Creative Build & Test", 1280, "3 days ago"),
                SaveInfo("Skyblock <hard>", 96, "Last month")]

    def diagnostics(self):
        return [CheckResult("Game files", "ok"),
                CheckResult("Graphics card", "warn", "Two GPUs found; pick one in Settings."),
                CheckResult("Wine prefix", "error", "Prefix looks damaged. Use Repair, your worlds are kept.")]

    state = "idle"

    def connect(self, listener):
        self._listeners = getattr(self, "_listeners", []) + [listener]
        return lambda: None

    def _emit(self, name, **payload):
        for listener in getattr(self, "_listeners", []):
            listener(name, payload)

    def start(self):
        pass

    def install_needed(self):
        return False

    def requirements(self):
        from .requirements import TEXT
        state = getattr(self, "_req", None)
        if state is None:
            state = self._req = {"engine": [True, 2_100_000_000], "xodus": [True, 38_000_000],
                                 "webview": [False, 0], "xcurl": [True, 21_000_000],
                                 "umu": [True, 9_000_000], "java": [False, 0], "proxypass": [False, 0],
                                 "login-deps": [True, 4_000_000], "cache": [True, 310_000_000]}
        out = []
        for cid, (installed, size) in state.items():
            title, text = TEXT[cid]
            out.append(RequirementInfo(cid, _(title), _(text), installed, size,
                                       "proxypass" if cid in ("java", "proxypass") else "all",
                                       installable=cid != "cache", removable=cid != "login-deps",
                                       busy=getattr(self, "_busy", {}).get(cid, ""),
                                       kind="cache" if cid == "cache" else "component"))
        return out

    def refresh_requirement_sizes(self):
        pass

    def _req_job(self, cid, installing):
        import threading
        import time
        self.requirements()
        self._busy = {**getattr(self, "_busy", {}), cid: "installing" if installing else "removing"}
        self._emit("component", id=cid, state="running")

        def work():
            if installing:
                for i in range(1, 21):
                    self._emit("component-progress", id=cid, done=i * 5_000_000, total=100_000_000)
                    time.sleep(0.08)
            else:
                time.sleep(0.8)
            self._req[cid] = [installing, 120_000_000 if installing else 0]
            self._busy.pop(cid, None)
            self._emit("component", id=cid, state="done")
            self._emit("requirements-changed")

        threading.Thread(target=work, daemon=True).start()

    def install_requirement(self, cid):
        self._req_job(cid, True)

    def remove_requirement(self, cid):
        self._req_job(cid, False)

    def proxy_missing(self):
        return []

    def needs_proxy_login(self):
        return False

    def proxy_skipped(self):
        return False

    def needs_store_login(self):
        return False

    def proxy_supported(self):
        return ["26.30", "26.20", "26.10"]

    def proxy_problem(self):
        if self.mode() != "proxypass" or self.selected_version() in ("26.30", "26.20", "26.10"):
            return None
        return ("ProxyPass has no build for Minecraft " + self.selected_version()
                + ". It works with: 26.30, 26.20, 26.10. Pick one of those versions, or use Normal mode.")

    def mode(self):
        return getattr(self, "_mode", "xodus")

    def set_mode(self, mode):
        self._mode = mode
        self._emit("mode-changed", mode=mode)

    def proxy_destination(self):
        return ("geo.hivebedrock.network", "19132")

    def needs_welcome(self):
        return False

    def install(self, on_status=None):
        """Pretend to install, so the setup screen can be seen without downloading."""
        import threading
        import time

        self.state = "preparing"

        def work():
            self._emit("play-state", state="preparing", message="")
            total = 2_400_000_000
            for stage, share in (("deps", 0.02), ("game", 0.7), ("engine", 0.2), ("prefix", 0.06), ("finish", 0.02)):
                self._emit("setup-stage", stage=stage)
                steps = max(int(share * 60), 3)
                for i in range(steps):
                    self._done = getattr(self, "_done", 0) + int(total * share / steps)
                    self._emit("progress", done=min(self._done, total), total=total)
                    time.sleep(0.08)
            self._done = 0
            self.state = "idle"
            self._emit("setup-done")
            self._emit("play-state", state="idle", message="")

        threading.Thread(target=work, daemon=True).start()

    def catalog_loaded(self):
        return True

    def catalog_failed(self):
        return False

    def reload_catalog(self): pass

    def set_channel(self, channel):
        pass

    def use_build(self, tag, channel): pass
    def remove_build(self, path): pass
    def sign_in_store(self): pass
    def store_login_running(self): return False
    def cancel_store_login(self): pass
    def sign_out_store(self): pass
    def sign_in_microsoft(self): pass
    def cancel_microsoft_login(self): pass
    def sign_out_microsoft(self): pass

    def open_logs(self): pass
    def repair(self): pass
    def force_stop(self): pass
    def refresh_diagnostics(self): pass

    def settings_groups(self):
        from .settings import Choice, build_groups
        return build_groups([Choice("0000:01:00.0", "NVIDIA GeForce RTX 4070 (0000:01:00.0)"),
                             Choice("0000:00:02.0", "Intel Graphics (0000:00:02.0) — runs the display")],
                            proxy_presets=[Choice("hive", "Hive")])

    def get_setting(self, key):
        stored = getattr(self, "_settings", {})
        if key in stored:
            return stored[key]
        from .settings import build_groups
        return next((i.default for g in build_groups() for i in g.items if i.key == key), None)

    def set_setting(self, key, value):
        self._settings = {**getattr(self, "_settings", {}), key: value}
        self._emit("setting-changed", key=key, value=value)

    def close_on_launch(self):
        return getattr(self, "_close", True)

    def set_close_on_launch(self, value):
        self._close = bool(value)
        self._emit("setting-changed", key="close_on_launch", value=bool(value))

    def stop(self):
        pass

    def play(self, on_status):
        on_status("Demo: nothing is launched.")


def __getattr__(name):  # LauncherController is imported lazily: it needs no GTK but is only used for real runs
    if name == "LauncherController":
        from .real import LauncherController
        return LauncherController
    raise AttributeError(name)
