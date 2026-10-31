"""The real controller: what the UI talks to when it runs for real.

No GTK imports. Everything that touches the user's files, the network or a
process goes through a *backend* object, so tests drive this class with a fake
and merely importing it never reads or writes anything.

Events (listeners are called from whatever thread produced them; the UI hops to
its main thread itself): ``catalog-changed``, ``builds-changed``,
``accounts-changed``, ``play-state`` {state, message}, ``progress`` {done, total},
``game-started`` {window_action}, ``game-closed``, ``notice`` {text},
``needs-store-signin`` {message}, ``error`` {title, message}, ``setting-changed``
{key, value}, ``component`` {id, state: running|done|refused}.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime
from typing import Callable

from .models import Account, BuildInfo, CheckResult, RequirementInfo, SaveInfo
from .requirements import TEXT as REQUIREMENT_TEXT
from .settings import Choice, build_groups
from gomceix.i18n import _

IDLE, PREPARING, RUNNING, STOPPING = "idle", "preparing", "running", "stopping"
MODES = ("xodus", "proxypass")
PROXY_KEYS = ("proxypass_host", "proxypass_port")
PROXY_SERVER_KEY = "proxypass_server"     # which preset (or "custom") the host and port amount to
PROXY_ONLINE_KEY = "proxypass_online"     # kept in ProxyPass's own config, like the server address


def _component_busy_text() -> str:
    return _("A component is still downloading or being removed. Wait for it to finish, then try again.")


class CoreBackend:
    """Late-bound facade over `gomceix.core` (imported on first use)."""

    def __init__(self):
        from gomceix.core import auth, games, gamesetup, launch, prefix, util, xodus
        self._m = (auth, games, gamesetup, launch, prefix, util, xodus)
        self.NotSignedIn = xodus.NotSignedIn

    def load_settings(self):
        return self._m[5].load_settings()

    def save_setting(self, key, value):
        util = self._m[5]
        settings = util.load_settings()
        settings[key] = value
        util.save_settings(settings)

    def list_editions(self):
        return self._m[1].list_editions(include_beta=True)

    def list_versions(self, edition_id, ignore_cache=False):
        return self._m[1].list_versions(edition_id, ignore_cache=ignore_cache)

    def installed_builds(self, with_size=False):
        return self._m[1].installed_builds(with_size=with_size)

    def do_setup(self, edition, tag, progress, stage=None):
        return self._m[2].do_setup(mc_edition=edition, mc_version=tag, progress=progress, stage=stage)

    def launch(self, on_started, notices):
        return self._m[3].launch(on_started=on_started, notices=notices)

    def exit_problem(self, rc):
        return self._m[3].exit_problem(rc)

    def list_worlds(self):
        from gomceix.core import saves
        return saves.list_worlds()

    def remove_build(self, path):
        return self._m[1].remove_build(path)

    def reset_prefix(self):
        return self._m[4].reset_prefix()

    def open_logs(self):
        import subprocess
        from gomceix.core.config import LOGS
        LOGS.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(LOGS)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def list_gpus(self):
        """[(slot, display label)] of the graphics cards; [] when none can be read."""
        from gomceix.core import gpus
        try:
            return [(g.slot, f"{g.name} ({g.slot})" + (" — runs the display" if g.boot_vga else ""))
                    for g in gpus.list_gpus()]
        except Exception:
            return []

    def single_window_session(self):
        return self._m[3].single_window_session()

    def kill_wine(self):
        return self._m[4].kill_wine()

    def display_version(self, tag, beta):
        return self._m[5].format_display_version(tag, beta)

    def store_signed_in(self):
        return self._m[6].signed_in()

    def msa_signed_in(self):
        return self._m[0].msa_signed_in()

    def msa_gamertag(self):
        return self._m[0].msa_gamertag()

    # --- sign-in flows
    @property
    def LoginCancelled(self):
        return self._m[6].LoginCancelled

    def store_login(self):
        return self._m[6].login()

    def store_cancel(self):
        return self._m[6].cancel_login()

    def store_logout(self):
        return self._m[6].logout()

    def msa_auth(self):
        return self._m[0].NativeAuth()

    # --- components (what Gomceix downloads for itself)
    def component_ids(self):
        from gomceix.core import components
        return components.IDS

    def component_info(self, component_id):
        """(installed, needed_for, shared) without measuring anything."""
        from gomceix.core import components
        comp = components.get(component_id)
        return comp.installed(), comp.needed_for, comp.is_shared()

    def component_size(self, component_id):
        from gomceix.core import components
        return components.size_bytes(component_id)

    def component_install(self, component_id, progress):
        from gomceix.core import components
        return components.install(component_id, progress)

    def component_remove(self, component_id):
        from gomceix.core import components
        return components.remove(component_id)

    # --- ProxyPass mode
    def proxy_auth(self):
        from gomceix.core import proxypass
        return proxypass.ProxyLogin()

    def proxy_supported(self):
        from gomceix.core import proxypass
        return proxypass.supported_versions()

    def proxy_problem(self, tag, versions):
        from gomceix.core import proxypass
        return proxypass.support_problem(tag, {v: True for v in versions})

    def proxy_presets(self):
        from gomceix.core import proxypass
        return [(pid, name, host, port) for pid, name, host, port in proxypass.SERVER_PRESETS]

    def proxy_signed_in(self):
        from gomceix.core import proxypass
        return proxypass.signed_in()

    def proxy_logout(self):
        from gomceix.core import proxypass
        return proxypass.sign_out()

    def proxy_online_mode(self):
        from gomceix.core import proxypass
        return proxypass.online_mode()

    def set_proxy_online_mode(self, enabled):
        from gomceix.core import proxypass
        return proxypass.write_online_mode(enabled)

    def proxy_destination(self):
        from gomceix.core import proxypass
        return proxypass.read_destination()

    def set_proxy_destination(self, host, port):
        from gomceix.core import proxypass
        return proxypass.write_destination(host, port)

    def msa_logout(self):
        return self._m[0].msa_logout()


def relative_day(timestamp: float, now: float | None = None) -> str:
    """'Today', 'Yesterday', '3 days ago', 'Last month' or a date: how a world's
    last save reads in a list. Calendar days, not 24-hour blocks."""
    if not timestamp:
        return _("Never played")
    now = time.time() if now is None else now
    days = (datetime.fromtimestamp(now).date() - datetime.fromtimestamp(timestamp).date()).days
    if days <= 0:
        return _("Today")
    if days == 1:
        return _("Yesterday")
    if days < 30:
        return _("{n} days ago", n=days)
    if days < 60:
        return _("Last month")
    return date.fromtimestamp(timestamp).isoformat()


def window_action(settings: dict, single_window: bool) -> str:
    """What the window does once the game process exists."""
    if (settings or {}).get("close_on_launch", False):
        return "close"
    return "step-aside" if single_window else "stay"


class LauncherController:
    def __init__(self, backend=None):
        self._b = backend or CoreBackend()
        self._listeners: list[Callable] = []
        self._lock = threading.RLock()
        self._state = IDLE
        self._catalog: list[dict] = []     # {tag, beta, edition, installed, label}
        self._catalog_loaded = False
        self._catalog_failed = False       # a fetch of the list failed (offline): "empty" then means "not reached"
        self._store_busy = False
        self._ms_auth = None
        self._proxy_versions: list | None = None     # game versions ProxyPass has a build for (None = not loaded)
        self._sizes: dict = {}
        self._component_busy: dict = {}
        self._repairing = False
        self._job_lock = threading.Lock()       # one download or removal at a time

    # ------------------------------------------------------------- events
    def connect(self, listener: Callable[[str, dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def _emit(self, name: str, **payload) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(name, payload)
            except Exception as exc:  # a broken listener must not break the session
                print(f"[controller] listener failed on {name!r}: {exc}")

    def _set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self._state = state
        self._emit("play-state", state=state, message=message)

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------ catalog
    def start(self) -> None:
        """Begin loading what is slow (the version catalogue) in the background."""
        threading.Thread(target=self.refresh_catalog, daemon=True).start()
        if self.mode() == "proxypass":
            self.refresh_proxy_support()

    def refresh_proxy_support(self) -> None:
        """Ask (in the background) which game versions ProxyPass has a build for."""
        def work():
            try:
                versions = list(self._b.proxy_supported())
            except Exception:
                versions = []
            with self._lock:
                self._proxy_versions = versions or None
            self._emit("proxy-support-changed")

        threading.Thread(target=work, daemon=True).start()

    def proxy_supported(self) -> list | None:
        """Display labels ('26.30') of the game versions ProxyPass works with; None while unknown."""
        versions = self._proxy_versions
        return None if not versions else [v.split(".", 1)[1] if v.startswith("1.") else v for v in versions]

    def proxy_problem(self) -> str | None:
        """Why the selected version cannot be played in ProxyPass mode (None: it can, or not known).
        With online mode off every version may be played: one without a build starts without the proxy."""
        if self.mode() != "proxypass" or not self._proxy_versions or not self._proxy_online():
            return None
        entry = self._selected_entry()
        if entry is None:
            return None
        return self._b.proxy_problem(entry["tag"], self._proxy_versions)

    def _proxy_online(self) -> bool:
        return bool(self._quiet(self._b.proxy_online_mode, True))

    def proxy_skipped(self) -> bool:
        """True when the selected version starts without ProxyPass: online mode is off and it has no build."""
        entry = self._selected_entry()
        if self.mode() != "proxypass" or self._proxy_online() or not self._proxy_versions or entry is None:
            return False
        return self._b.proxy_problem(entry["tag"], self._proxy_versions) is not None

    def refresh_catalog(self, ignore_cache: bool = False) -> None:
        entries = []
        failed = False
        try:
            editions = self._b.list_editions()
        except Exception as exc:
            self._emit("error", title=_("Could not read the version list"), message=str(exc))
            editions = []
            failed = True
        for edition in editions:
            try:
                builds = self._b.list_versions(edition["id"], ignore_cache=ignore_cache)
            except Exception as exc:
                # One unreachable catalogue costs that edition, not the whole list.
                print(f"[controller] no versions for {edition.get('id')}: {exc}")
                failed = True
                continue
            beta = bool(edition.get("beta", False))
            for build in builds:
                tag = build["version"]
                entries.append({"tag": tag, "beta": beta, "edition": edition,
                                "installed": bool(build.get("installed")),
                                "label": self._b.display_version(tag, beta)})
        for beta in (False, True):                  # two builds must never read the same
            group = [e for e in entries if e["beta"] == beta]
            seen: dict = {}
            for e in group:
                seen[e["label"]] = seen.get(e["label"], 0) + 1
            for e in group:
                if seen[e["label"]] > 1:
                    e["label"] = f"{e['label']} ({e['tag']})"
        with self._lock:
            self._catalog = entries
            self._catalog_failed = failed
            self._catalog_loaded = True
        self._emit("catalog-changed")

    def catalog_loaded(self) -> bool:
        return self._catalog_loaded

    def catalog_failed(self) -> bool:
        """True when the last fetch of the version list failed, so an empty list means "not reached"."""
        return self._catalog_failed

    def reload_catalog(self) -> None:
        """Fetch the version list again (the first run offline has nothing cached to show)."""
        with self._lock:
            self._catalog_loaded = False                 # the pages say "Loading versions…" meanwhile
        self._emit("catalog-changed")
        threading.Thread(target=self.refresh_catalog, args=(True,), daemon=True).start()

    def channel(self) -> str:
        return "Preview" if self._b.load_settings().get("show_betas") else "Stable"

    def _save(self, key: str, value) -> bool:
        """Save one setting. A folder that cannot be written is told to the user and the
        pages draw the stored value again; False means nothing was saved."""
        try:
            self._b.save_setting(key, value)
        except Exception as exc:
            self._emit("error", title=_("Could not save the setting"), message=str(exc) or type(exc).__name__)
            self._emit("setting-rejected", key=key)
            return False
        return True

    def set_channel(self, channel: str) -> None:
        self._save("show_betas", channel == "Preview")
        self._emit("catalog-changed")                        # also puts the stored channel back when it was not saved

    def _channel_entries(self) -> list[dict]:
        want_beta = self.channel() == "Preview"
        return [e for e in self._catalog if e["beta"] == want_beta]

    def _visible_entries(self) -> list[dict]:
        """What the version list offers: in ProxyPass online mode only the versions it has a build for."""
        entries = self._channel_entries()
        known = self._proxy_versions
        if self.mode() != "proxypass" or not known or not self._proxy_online():
            return entries
        return [e for e in entries if self._b.proxy_problem(e["tag"], known) is None]

    def versions(self) -> list[str]:
        return [e["label"] for e in self._visible_entries()]

    def _selected_entry(self):
        entries = self._channel_entries()
        if not entries:
            return None
        wanted = (self._b.load_settings().get("mc_version") or "").strip()
        if wanted:
            for entry in entries:
                if entry["tag"] == wanted:
                    return entry
            # Older settings files saved the short label or a partial version.
            for entry in entries:
                if entry["tag"].startswith(wanted + ".") or entry["label"] == wanted:
                    return entry
        return (self._visible_entries() or entries)[0]

    def selected_version(self) -> str:
        entry = self._selected_entry()
        return entry["label"] if entry else ""

    def set_version(self, label: str) -> None:
        for entry in self._channel_entries():
            if entry["label"] == label:
                # The exact build id is what a selection is: saving the display
                # label once caused a silent multi-GB re-download.
                self._save("mc_version", entry["tag"])
                return

    # ---------------------------------------------------------- maintenance
    def open_logs(self) -> None:
        try:
            self._b.open_logs()
        except Exception as exc:
            self._emit("error", title=_("Could not open the logs folder"), message=str(exc) or type(exc).__name__)

    def repair(self) -> None:
        """Reset the Wine prefix (worlds and settings are kept). The caller has
        already asked the user: this stops a running game."""
        with self._lock:
            if self._repairing:                 # a second click must not start a second reset
                return
            self._repairing = True

        def work():
            self._emit("maintenance", job="repair", state="running")
            try:
                self._b.reset_prefix()
            except Exception as exc:
                self._emit("maintenance", job="repair", state="failed")
                self._emit("error", title=_("Repair failed"), message=str(exc) or type(exc).__name__)
                return
            finally:
                with self._lock:
                    self._repairing = False
            self._emit("maintenance", job="repair", state="done")

        threading.Thread(target=work, daemon=True).start()

    def force_stop(self) -> None:
        """Close the game's processes now, whoever started them."""
        def work():
            try:
                self._b.kill_wine()
            except Exception as exc:
                self._emit("error", title=_("Could not stop Minecraft"), message=str(exc) or type(exc).__name__)
            self._emit("maintenance", job="force-stop", state="done")

        threading.Thread(target=work, daemon=True).start()

    def refresh_diagnostics(self) -> None:
        self._emit("accounts-changed")      # the pages that show health rebuild from fresh data

    # ----------------------------------------------------------- settings
    def settings_groups(self):
        return build_groups((Choice(slot, label) for slot, label in self._b.list_gpus()),
                            proxy_presets=[Choice(pid, name) for pid, name, _h, _p in self._b.proxy_presets()])

    def _preset_id(self) -> str:
        """The preset the ProxyPass server address amounts to, else "custom"."""
        host, port = self._b.proxy_destination()
        return next((pid for pid, _n, phost, pport in self._b.proxy_presets()
                     if str(host).strip().lower() == phost and str(port).strip() == pport), "custom")

    def get_setting(self, key: str):
        if key == PROXY_SERVER_KEY:
            return self._preset_id()
        if key == PROXY_ONLINE_KEY:
            return self._b.proxy_online_mode()
        if key in PROXY_KEYS:
            return self._b.proxy_destination()[PROXY_KEYS.index(key)]
        stored = self._b.load_settings()
        if key in stored:
            return stored[key]
        for group in build_groups():
            for item in group.items:
                if item.key == key:
                    return item.default
        return None

    def set_setting(self, key: str, value) -> None:
        if key == PROXY_ONLINE_KEY:
            try:
                self._b.set_proxy_online_mode(bool(value))
            except Exception as exc:
                self._emit("error", title=_("Could not change online mode"), message=str(exc))
                self._emit("setting-rejected", key=key)
                return
            self._emit("setting-changed", key=key, value=bool(value))
            self._emit("accounts-changed")                   # the ProxyPass sign-in comes or goes
            self._emit("catalog-changed")                    # and so does the limit on the version list
            return
        if key == PROXY_SERVER_KEY or key in PROXY_KEYS:
            if key == PROXY_SERVER_KEY:
                chosen = next(((h, p) for pid, _n, h, p in self._b.proxy_presets() if pid == value), None)
                if chosen is None:               # "custom": the address below stays as it is
                    return
                host, port = chosen
            else:
                host, port = self._b.proxy_destination()
                host, port = (value, port) if key == PROXY_KEYS[0] else (host, value)
            try:
                self._b.set_proxy_destination(host, port)
            except Exception as exc:
                self._emit("error", title=_("Could not save the server address"), message=str(exc))
                self._emit("setting-rejected", key=key)      # the page puts the old value back
                return
            self._emit("proxy-destination-changed")          # the Play note and the preset row follow
            return
        if self._save(key, value):
            self._emit("setting-changed", key=key, value=value)

    def close_on_launch(self) -> bool:
        return bool(self._b.load_settings().get("close_on_launch", False))

    def set_close_on_launch(self, value: bool) -> None:
        if self._save("close_on_launch", bool(value)):
            self._emit("setting-changed", key="close_on_launch", value=bool(value))

    def needs_welcome(self) -> bool:
        """A brand-new user: no Store account and no game on disk yet."""
        try:
            return not self._b.store_signed_in() and not self._b.installed_builds(with_size=False)
        except Exception:
            return False

    # ----------------------------------------------------------- accounts
    # ------------------------------------------------------- requirements
    CACHE = "cache"

    def requirements(self) -> list[RequirementInfo]:
        """Every component with its state. Sizes appear once `refresh_requirement_sizes` has measured them."""
        out = []
        for cid in self._b.component_ids():
            try:
                installed, needed_for, shared = self._b.component_info(cid)
            except Exception:
                installed, needed_for, shared = False, "all", False
            title, text = REQUIREMENT_TEXT.get(cid, (cid, ""))      # a component the UI has no text for yet
            out.append(RequirementInfo(cid, _(title), _(text) if text else "", bool(installed), self._sizes.get(cid),
                                       needed_for, installable=True, removable=not shared,
                                       busy=self._component_busy.get(cid, "")))
        title, text = REQUIREMENT_TEXT[self.CACHE]
        size = self._sizes.get(self.CACHE)
        out.append(RequirementInfo(self.CACHE, _(title), _(text), bool(size), size, "all",
                                   installable=False, removable=True,
                                   busy=self._component_busy.get(self.CACHE, ""), kind="cache"))
        return out

    def refresh_requirement_sizes(self) -> None:
        def work():
            for cid in (*self._b.component_ids(), self.CACHE):
                try:
                    self._sizes[cid] = int(self._b.component_size(cid))
                except Exception:
                    self._sizes[cid] = None
            self._emit("requirements-sizes")

        threading.Thread(target=work, daemon=True).start()

    def _component_job(self, cid: str, kind: str, work, error_title: str, then=None) -> None:
        with self._lock:
            if cid in self._component_busy:
                refused = ""                       # the same job is already running: nothing to add
            elif self._state != IDLE:
                refused = _("Wait until Minecraft has stopped or finished preparing, then try again.")
            else:
                refused = None
                self._component_busy[cid] = kind
        if refused is not None:
            # Always answer: a page that queued this job (Download missing)
            # would otherwise wait forever for a "done" that never comes.
            if refused:
                self._emit("error", title=error_title, message=refused)
            self._emit("component", id=cid, state="refused")
            return
        self._emit("component", id=cid, state="running")

        def run():
            succeeded = False
            try:
                with self._job_lock:
                    work()
                succeeded = True
            except Exception as exc:
                self._emit("error", title=error_title, message=str(exc) or type(exc).__name__)
            finally:
                with self._lock:
                    self._component_busy.pop(cid, None)
                try:
                    self._sizes[cid] = int(self._b.component_size(cid))
                except Exception:
                    self._sizes[cid] = None
                self._emit("component", id=cid, state="done")
                self._emit("requirements-changed")
            if succeeded and then is not None:       # the next step only runs when this one worked
                try:
                    then()
                except Exception as exc:
                    self._emit("error", title=error_title, message=str(exc) or type(exc).__name__)

        threading.Thread(target=run, daemon=True).start()

    def install_requirement(self, cid: str, then=None) -> None:
        self._component_job(
            cid, "installing",
            lambda: self._b.component_install(
                cid, lambda got, total: self._emit("component-progress", id=cid, done=got, total=total)),
            _("Download failed"), then)

    PROXY_REQUIREMENTS = ("java", "proxypass")

    def proxy_missing(self) -> list[str]:
        """The ProxyPass prerequisites (Java, the proxy) that are not downloaded yet."""
        missing = []
        for cid in self.PROXY_REQUIREMENTS:
            try:
                installed = self._b.component_info(cid)[0]
            except Exception:
                installed = False
            if not installed:
                missing.append(cid)
        return missing

    def _install_in_order(self, ids: list[str], then) -> None:
        def step(i: int) -> None:
            if i >= len(ids):
                then()
            else:
                self.install_requirement(ids[i], then=lambda: step(i + 1))
        step(0)

    def remove_requirement(self, cid: str) -> None:
        self._component_job(cid, "removing", lambda: self._b.component_remove(cid), _("Could not remove it"))

    # ------------------------------------------------------------- mode
    def mode(self) -> str:
        """"xodus" (normal: the launcher signs the game in) or "proxypass"."""
        mode = self._b.load_settings().get("login_mode")
        return mode if mode in MODES else "xodus"

    def set_mode(self, mode: str) -> None:
        with self._lock:
            if mode not in MODES or self._state != IDLE or mode == self.mode():
                return
        self.cancel_microsoft_login()            # a code issued for the other mode would link the wrong account
        if not self._save("login_mode", mode):
            return                                           # the mode did not change: the page shows the real one
        if mode == "proxypass" and self._proxy_versions is None:
            self.refresh_proxy_support()
        self._emit("mode-changed", mode=mode)
        self._emit("accounts-changed")

    def proxy_destination(self) -> tuple[str, str]:
        return self._b.proxy_destination()

    @staticmethod
    def _quiet(call, default=None):
        """A sign-in state that cannot be read counts as signed out: the page still has to draw."""
        try:
            return call()
        except Exception as exc:
            print(f"[controller] could not read an account state: {exc}")
            return default

    def accounts(self) -> list[Account]:
        store = Account("store", bool(self._quiet(self._b.store_signed_in, False)), None,
                        _("Needed to download the game"))
        if self.mode() == "proxypass":
            if not self._proxy_online():
                return [store]                               # nothing to sign in to
            signed = bool(self._quiet(self._b.proxy_signed_in, False))
            return [Account("proxypass", signed, _("ProxyPass") if signed else None,
                            _("Needed to play online in ProxyPass mode")), store]
        microsoft = bool(self._quiet(self._b.msa_signed_in, False))
        name = self._quiet(self._b.msa_gamertag) if microsoft else None
        return [Account("microsoft", microsoft, name, _("Needed to play online")), store]

    def account_name(self):
        return next((a.name for a in self.accounts() if a.kind in ("microsoft", "proxypass") and a.name), None)

    def needs_store_login(self) -> bool:
        """True when the selected version must be downloaded and no Store account is signed in."""
        entry = self._selected_entry()
        if entry is None or entry.get("installed"):
            return False
        try:
            return not self._b.store_signed_in()
        except Exception:
            return False

    def needs_proxy_login(self) -> bool:
        """True in ProxyPass online mode while ProxyPass has no signed-in account."""
        if self.mode() != "proxypass":
            return False
        try:
            return self._b.proxy_online_mode() and not self._b.proxy_signed_in()
        except Exception:
            return False

    def _sign_in_first(self, then) -> None:
        """Ask for the Store login before a download; `then` continues once it succeeded."""
        self._emit("toast", text=_("Sign in to your Microsoft Store account first. The download starts when you are signed in."))
        self.sign_in_store(then=then)

    def sign_in_store(self, then=None) -> None:
        """Open the Store sign-in window (blocks a worker, not the UI). `then` runs after a successful sign-in."""
        with self._lock:
            if self._store_busy:
                return
            self._store_busy = True
        self._emit("store-login", state="running")

        def work():
            state = "done"
            try:
                self._b.store_login()
            except self._b.LoginCancelled:
                state = "cancelled"
            except Exception as exc:
                state = "failed"
                self._emit("error", title=_("Store sign-in failed"), message=str(exc) or type(exc).__name__)
            finally:
                with self._lock:
                    self._store_busy = False
                self._emit("store-login", state=state)
                self._emit("accounts-changed")
            if state == "done" and then is not None:
                try:
                    then()
                except Exception as exc:
                    self._emit("error", title=_("Minecraft could not start"), message=str(exc) or type(exc).__name__)

        threading.Thread(target=work, daemon=True).start()

    def store_login_running(self) -> bool:
        """True while the Store sign-in window is open (a rebuilt page asks, to show Cancel)."""
        return self._store_busy

    def cancel_store_login(self) -> None:
        try:
            self._b.store_cancel()
        except Exception as exc:
            self._emit("error", title=_("Could not cancel the sign-in"), message=str(exc))

    def sign_out_store(self) -> None:
        self._run_account_job(self._b.store_logout, _("Could not sign out of the Store"))

    def sign_in_microsoft(self, then=None) -> None:
        """Start the device-code sign-in: emits `ms-code` {url, code}, then
        `ms-code-done` {linked} when it ends (or is cancelled)."""
        if self.mode() == "proxypass":
            missing = self.proxy_missing()
            if missing:
                # Java and the proxy are needed before there is anything to sign in to:
                # fetch them now, visibly, and start the sign-in once they are in place.
                self._emit("toast", text=_("Downloading Java and ProxyPass first. The sign-in starts when they are ready."))
                self._install_in_order(missing, lambda: self.sign_in_microsoft(then=then))
                return
        with self._lock:
            if self._ms_auth is not None:
                return
            proxy = self.mode() == "proxypass"
            try:
                auth = self._b.proxy_auth() if proxy else self._b.msa_auth()
            except Exception as exc:
                auth = None
                problem = str(exc) or type(exc).__name__
            else:
                self._ms_auth = auth
        if auth is None:
            self._emit("error", title=_("ProxyPass sign-in failed") if proxy else _("Microsoft sign-in failed"),
                       message=problem)
            return

        def current() -> bool:
            with self._lock:
                return self._ms_auth is auth

        def finish(linked):
            with self._lock:
                if self._ms_auth is not auth:       # cancelled (or replaced) meanwhile: already announced
                    return
                self._ms_auth = None
            self._emit("ms-code-done", linked=linked)
            self._emit("accounts-changed")
            if linked and then is not None:      # e.g. the game that was waiting for this sign-in
                try:
                    then()
                except Exception as exc:
                    self._emit("error", title=_("Minecraft could not start"), message=str(exc) or type(exc).__name__)

        def failed(message):
            if current():
                self._emit("error", title=_("ProxyPass sign-in failed") if proxy else _("Microsoft sign-in failed"),
                           message=message)
            finish(False)

        def on_code(url, code):
            if current():                           # a code that arrives after Cancel must not reopen the dialog
                self._emit("ms-code", url=url, code=code)

        try:
            auth.start(on_auth=on_code, on_online=lambda: finish(True), on_error=failed)
        except Exception as exc:                    # never leave the sign-in "in progress" for good
            with self._lock:
                if self._ms_auth is auth:
                    self._ms_auth = None
            self._emit("error", title=_("ProxyPass sign-in failed") if proxy else _("Microsoft sign-in failed"),
                       message=str(exc) or type(exc).__name__)
            self._emit("ms-code-done", linked=False)

    def cancel_microsoft_login(self) -> None:
        with self._lock:
            auth, self._ms_auth = self._ms_auth, None
        if auth is not None:
            try:
                auth.stop()
            except Exception as exc:
                print(f"[controller] could not stop the sign-in: {exc}")
            self._emit("ms-code-done", linked=False)

    def sign_out_microsoft(self) -> None:
        if self.mode() == "proxypass":
            self._run_account_job(self._b.proxy_logout, _("Could not sign out of ProxyPass"))
        else:
            self._run_account_job(self._b.msa_logout, _("Could not sign out of Microsoft"))

    def _run_account_job(self, job, error_title: str) -> None:
        def work():
            try:
                job()
            except Exception as exc:
                self._emit("error", title=error_title, message=str(exc) or type(exc).__name__)
            self._emit("accounts-changed")

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------- builds
    def _safe_installed_builds(self) -> list:
        try:
            return list(self._b.installed_builds(with_size=False) or [])
        except Exception as exc:
            print(f"[controller] could not list the installed builds: {exc}")
            return []

    def builds(self) -> list[BuildInfo]:
        """Installed builds. `selected` is the build PLAY would start: the one the
        Play page shows (the core's `in_use` only follows it once a PLAY has set the
        game folder up). A game is running on a build the core calls `in_use`."""
        running = self._state in (RUNNING, STOPPING)
        current = self._selected_entry()
        out = []
        for build in self._safe_installed_builds():
            size = build.get("size")
            tag = str(build.get("version") or build.get("name") or "?")
            preview = build.get("edition") == "preview"
            selected = (bool(build.get("in_use")) if current is None
                        else tag == current["tag"] and preview == current["beta"])
            out.append(BuildInfo(
                version=self._b.display_version(tag, preview), channel="Preview" if preview else "Stable",
                size_mb=None if not size else int(size) // (1024 * 1024),
                selected=selected, in_use=bool(build.get("in_use")) and running,
                path=str(build.get("path") or ""), tag=tag))
        return out

    def use_build(self, tag: str, channel: str) -> None:
        """Make an installed build the one PLAY starts."""
        if self._save("show_betas", channel == "Preview") and self._save("mc_version", tag):
            self._emit("catalog-changed")
            self._emit("builds-changed")

    def remove_build(self, path: str) -> None:
        """Delete one downloaded build (worlds and settings are not in it)."""
        with self._lock:
            busy = self._state != IDLE
        if busy and any(b.get("in_use") and str(b.get("path") or "") == str(path)
                        for b in self._safe_installed_builds()):
            # The selected build is the one being prepared or played: deleting it
            # under a live game would leave a launch that can never finish.
            self._emit("error", title=_("Could not remove the version"),
                       message=_("Wait until Minecraft has stopped or finished preparing, then try again."))
            return

        def work():
            try:
                self._b.remove_build(path)
            except Exception as exc:
                self._emit("error", title=_("Could not remove the version"), message=str(exc) or type(exc).__name__)
            self._emit("builds-changed")

        threading.Thread(target=work, daemon=True).start()

    def saves(self) -> list[SaveInfo]:
        try:
            worlds = self._b.list_worlds()
        except Exception as exc:
            print(f"[controller] could not list worlds: {exc}")
            return []
        return [SaveInfo(name=w["name"], size_mb=None if w.get("size") is None else int(w["size"]) // (1024 * 1024),
                         last_played=relative_day(w.get("modified") or 0),
                         edition=_("Preview") if w.get("edition") == "preview" else "")
                for w in worlds]

    def diagnostics(self) -> list[CheckResult]:
        checks = []
        installed = self._safe_installed_builds()
        checks.append(CheckResult(_("Game files"), "ok") if installed else
                      CheckResult(_("Game files"), "warn",
                                  _("No game is installed yet. Press Play to download it.")))
        acc = {a.kind: a for a in self.accounts()}
        checks.append(CheckResult(_("Store account"), "ok") if acc["store"].signed_in else
                      CheckResult(_("Store account"), "warn",
                                  _("Sign in on the Accounts page to download the game.")))
        online = acc.get("proxypass") or acc.get("microsoft")      # which one exists depends on the mode
        title = _("ProxyPass account") if "proxypass" in acc else _("Microsoft account")
        if online:                                           # none in ProxyPass with online mode off
            checks.append(CheckResult(title, "ok") if online.signed_in else
                          CheckResult(title, "warn", _("Sign in to play online; offline play still works.")))
        return checks

    # --------------------------------------------------------- play / stop
    def play(self, on_status: Callable[[str], None] | None = None) -> None:
        if self._state == IDLE and self.needs_store_login():
            self._sign_in_first(lambda: self.play(on_status))
            return
        if self._state == IDLE and self.needs_proxy_login() and not self.proxy_problem():
            # ProxyPass would otherwise wait for a sign-in nobody can see.
            self._emit("toast", text=_("Sign in with ProxyPass first. The game starts when you are signed in."))
            self.sign_in_microsoft(then=lambda: self.play(on_status))
            return
        with self._lock:
            if self._state != IDLE:
                if on_status:
                    on_status(_("Minecraft is already starting or running."))
                return
            if self._component_busy:
                if on_status:
                    on_status(_component_busy_text())
                return
            entry = self._selected_entry()
            if entry is None:
                if on_status:
                    on_status(_("No version is available to play yet."))
                return
            problem = self.proxy_problem()
            if problem:
                if on_status:
                    on_status(problem)
                return
            self._state = PREPARING
        self._set_state(PREPARING, _("Preparing Minecraft…"))
        if self.install_needed():
            self._emit("open-setup")             # a first install is shown on the setup screen
        threading.Thread(target=self._run_session, args=(entry,), daemon=True).start()

    def install_needed(self) -> bool:
        """True while no game build is on disk: PLAY will start with a full install."""
        try:
            return not self._b.installed_builds(with_size=False)
        except Exception:
            return False

    def _setup(self, entry: dict) -> None:
        self._emit("setup-stage", stage="deps")
        self._b.do_setup(entry["edition"], entry["tag"],
                         lambda got, total: self._emit("progress", done=got, total=total),
                         lambda name: self._emit("setup-stage", stage=name))
        self._emit("setup-done")
        self._emit("builds-changed")           # the Library and the health checks now see the new build

    def install(self, on_status: Callable[[str], None] | None = None) -> None:
        """Download and prepare the selected version without starting it."""
        if self._state == IDLE and self.needs_store_login():
            self._sign_in_first(lambda: self.install(on_status))
            return
        with self._lock:
            if self._state != IDLE:
                if on_status:
                    on_status(_("Minecraft is already starting or running."))
                return
            if self._component_busy:
                if on_status:
                    on_status(_component_busy_text())
                return
            entry = self._selected_entry()
            if entry is None:
                if on_status:
                    on_status(_("No version is available to play yet."))
                return
            problem = self.proxy_problem()
            if problem:
                if on_status:
                    on_status(problem)
                return
            self._state = PREPARING
        self._set_state(PREPARING, _("Installing Minecraft…"))
        self._emit("open-setup")

        def work():
            try:
                self._setup(entry)
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                if isinstance(exc, self._b.NotSignedIn):
                    self._emit("needs-store-signin", message=message)
                else:
                    self._emit("error", title=_("Installation failed"), message=message)
                self._emit("setup-failed", message=message)
            finally:
                self._set_state(IDLE)

        threading.Thread(target=work, daemon=True).start()

    def _run_session(self, entry: dict) -> None:
        try:
            self._setup(entry)
            action = window_action(self._b.load_settings(), self._b.single_window_session())

            def started():
                self._set_state(RUNNING, _("Minecraft is running."))
                self._emit("game-started", window_action=action)

            notices: list[str] = []
            code = None
            try:
                code = self._b.launch(started, notices)
            finally:
                self._emit("game-closed")
            # A close the user asked for (Stop) is not a crash.
            problem = None if self._state == STOPPING else self._b.exit_problem(code)
            if problem:
                self._emit("game-problem", message=problem, code=code)
            for text in notices:
                self._emit("notice", text=text)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if isinstance(exc, self._b.NotSignedIn):
                self._emit("needs-store-signin", message=message)
            else:
                self._emit("error", title=_("Minecraft could not start"), message=message)
        finally:
            self._set_state(IDLE)

    def stop(self) -> None:
        with self._lock:
            if self._state != RUNNING:
                return
            self._state = STOPPING
        self._set_state(STOPPING, _("Stopping Minecraft…"))

        def work():
            try:
                self._b.kill_wine()
            except Exception as exc:
                self._emit("error", title=_("Could not stop Minecraft"), message=str(exc))

        threading.Thread(target=work, daemon=True).start()
