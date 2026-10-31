"""The downloads Gomceix keeps for itself, each installable and removable on its own.

Everything lives under the launcher's own data folder, so removing a component
never touches the system or other programs. Game builds, worlds and the Wine
prefix are not components: they have their own pages (Library, Saves, Repair).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config, proxypass
from .log import BolError, warn
from .util import load_settings, remove_path, save_settings


@dataclass(frozen=True)
class Component:
    id: str
    paths: Callable[[], tuple]                      # what removal deletes, all inside DATA
    installed: Callable[[], bool]
    install: Callable[[Callable | None], object] | None
    needed_for: str = "all"                         # "all" | "proxypass"
    shared: bool = False                            # installed system-wide: never removed from here
    system: Callable[[], bool] | None = None        # the host provides it right now (nothing of ours to remove)
    engine: bool = False                            # removal also needs the engine lock

    def is_shared(self) -> bool:
        return self.shared or bool(self.system and self.system())


def _engine_installed():
    return (config.WINEGDK_OUT / "proton").is_file()


def _install_engine(progress):
    from .winegdk import ensure_winegdk
    return ensure_winegdk(False, progress)


def _install_xodus(_progress):
    from . import xodus
    return xodus.ensure_cli()


def _xodus_installed():
    from . import xodus
    return xodus.cli_available()


def _install_webview(_progress):
    from . import webview
    return webview.ensure_runtime()


def _webview_installed():
    from . import webview
    return webview.installed() or webview.host_works_isolated()


def _webview_from_system():
    """The host's WebKitGTK is used and no bundle is unpacked: only then is there nothing to remove."""
    from . import webview
    return not webview.installed() and webview.host_works_isolated()


def _xcurl_installed():
    return (config.OPENSSL_XCURL_SET / "libcurl-4.dll").exists()


def _install_xcurl(_progress):
    from .fixups import ensure_openssl_xcurl_set
    return ensure_openssl_xcurl_set()


def _install_umu(_progress):
    from .prefix import ensure_umu
    return ensure_umu()


def _login_deps_installed():
    from . import deps
    return not deps.missing_login_deps()


def _install_login_deps(_progress):
    from . import deps
    return deps.ensure_login_deps()


def _java_installed():
    return bool(proxypass.find_java())


COMPONENTS = (
    Component("engine", lambda: (config.WINEGDK_OUT,), _engine_installed, _install_engine, engine=True),
    Component("xodus", lambda: (config.XODUS_DIR,), _xodus_installed, _install_xodus),
    Component("webview", lambda: (config.XODUS_WEBVIEW_DIR,), _webview_installed, _install_webview,
              system=_webview_from_system),
    Component("xcurl", lambda: (config.DATA / "xodus-xcurl",), _xcurl_installed, _install_xcurl),
    Component("umu", lambda: (config.UMU_DIR,), lambda: (config.UMU_DIR / "umu-run").is_file(), _install_umu),
    Component("java", lambda: (proxypass._java_root(),), _java_installed,
              lambda p: proxypass.ensure_java(p), needed_for="proxypass"),
    Component("proxypass", lambda: tuple(proxypass.PROXY_DIR.glob("ProxyPass*.jar")), proxypass.any_jar,
              lambda p: proxypass.ensure_jar(p), needed_for="proxypass"),
    Component("login-deps", lambda: (), _login_deps_installed, _install_login_deps, shared=True),
)
CACHE_ID = "cache"        # not a component: a folder that can be emptied
IDS = tuple(c.id for c in COMPONENTS)


def get(component_id: str) -> Component:
    for c in COMPONENTS:
        if c.id == component_id:
            return c
    raise BolError(f"Unknown component '{component_id}'.")


def tree_size(path) -> int:
    """Bytes under `path` (links are not followed); 0 when it does not exist."""
    path = Path(path)
    total = 0
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
        for root, _dirs, files in os.walk(path, followlinks=False):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def size_bytes(component_id: str) -> int:
    if component_id == CACHE_ID:
        return tree_size(config.CACHE)
    return sum(tree_size(p) for p in get(component_id).paths())


def _inside_data(path: Path) -> bool:
    data = Path(config.DATA).resolve()
    try:
        parent = path.parent.resolve()
    except OSError:
        return False
    return path != data and (parent == data or data in parent.parents)


def remove(component_id: str) -> None:
    """Delete one component (or empty the cache). Refuses while a game or setup runs."""
    from .engine_lock import managed_engine_lock
    from .prefix import prefix_operation_lock, shared_assets_lock
    if component_id == CACHE_ID:
        targets, engine = [p for p in Path(config.CACHE).glob("*")] if Path(config.CACHE).is_dir() else [], False
        comp_needs_proxy = False
    else:
        comp = get(component_id)
        if comp.is_shared():
            raise BolError("This component is shared with the system and is not removed from here.")
        targets, engine = list(comp.paths()), comp.engine
        comp_needs_proxy = comp.needed_for == "proxypass"
    for target in targets:
        if not _inside_data(Path(target)):
            raise BolError(f"Refusing to delete {target}: it is outside the Gomceix data folder.")
    if comp_needs_proxy and proxypass.session_running():
        raise BolError("ProxyPass is running (a sign-in or a game is using it). "
                       "Close it before removing this component.")
    with shared_assets_lock("remove a component", exclusive=True), prefix_operation_lock("remove a component"):
        if engine:
            with managed_engine_lock(config.PROTON_DIR):
                for target in targets:
                    _remove_target(target)
                _forget_engine(targets)
        else:
            for target in targets:
                _remove_target(target)


def _remove_target(target) -> None:
    """remove_path, retried once (something may still be writing into a folder
    being emptied), and failing as a BolError the front end can show."""
    for attempt in (1, 2):
        try:
            remove_path(target)
            return
        except OSError as exc:
            if attempt == 2:
                raise BolError(f"Could not remove {target}: {exc.strerror or exc}. "
                               "Close anything using it and try again.") from exc


def _forget_engine(removed) -> None:
    """Drop the settings that name an engine which no longer exists, so the next
    launch says "run Install / Update" instead of failing deep inside Wine."""
    try:
        settings = load_settings()
        current = settings.get("proton")
        gone = {Path(t).resolve() for t in removed}
        if current and Path(current).expanduser().resolve() in gone:
            settings.pop("proton", None)
            settings.pop("proton_tag", None)
            save_settings(settings)
    except Exception as exc:            # the files are already gone: report, do not undo
        warn(f"Removed the engine, but could not update the settings ({exc}).")


def install(component_id: str, progress=None) -> None:
    comp = get(component_id)
    if comp.install is None:
        raise BolError("This component cannot be installed from here.")
    comp.install(progress)
    if not comp.installed():
        raise BolError("The download finished, but the component is still not usable. "
                       "Check the log folder for details.")
