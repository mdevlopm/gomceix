"""ProxyPass mode: a local Java proxy that signs in to Xbox Live for the game.

In this mode the game itself starts signed out. ProxyPass listens on
127.0.0.1 and forwards to the server the player chose, authenticating with
the player's own Microsoft account. Nothing here touches the Xodus (Store)
path; it only needs a Java runtime and the ProxyPass jar, both downloaded
into the launcher's data folder on first use.
"""
from __future__ import annotations

import atexit
import errno
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import weakref
import zipfile
from pathlib import Path

from gomceix.i18n import _

from . import util
from .config import DATA, LOGS
from .log import BolError, info, warn

MODE_KEY = "login_mode"
MODES = ("xodus", "proxypass")
DEFAULT_MODE = "xodus"

PROXY_DIR = DATA / "proxypass"
RUNTIME_DIR = DATA / "runtime"
JAR = PROXY_DIR / "ProxyPass.jar"
JAVA_MAJOR = 25                       # the jar is built for Java 25
# Adoptium's own listing of the newest JRE: it names the file and gives the
# SHA-256 the download is checked against.
JAVA_ASSETS_URL = (f"https://api.adoptium.net/v3/assets/latest/{JAVA_MAJOR}/hotspot"
                   "?architecture=x64&image_type=jre&os=linux&vendor=eclipse")
JAR_REPO = "Kas-tle/ProxyPass"
LISTEN_PORT = "19132"

_JAVA_FLAGS = [
    "-Djava.net.preferIPv4Stack=true",
    "-XX:+IgnoreUnrecognizedVMOptions",
    "--add-opens", "java.base/jdk.internal.misc=ALL-UNNAMED",
    "--add-opens", "java.base/java.nio=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED",
    "-Dio.netty.tryReflectionSetAccessible=true",
]
_LOCK = threading.Lock()
STARTUP_CHECK_S = 2.0                 # how long start() watches for an instant crash
STOP_GRACE_S = 4.0
_SESSIONS: "weakref.WeakSet[ProxySession]" = weakref.WeakSet()
_LOG_CAP = 8 << 20
SESSIONS_KEPT = 10                    # ProxyPass writes a folder (about 0.5 MB, the skin) per connection


def current_mode(settings=None) -> str:
    s = util.load_settings() if settings is None else settings
    mode = s.get(MODE_KEY)
    return mode if mode in MODES else DEFAULT_MODE


# ------------------------------------------------------------- components
def _java_root() -> Path:
    return RUNTIME_DIR / f"java-{JAVA_MAJOR}"


def _java_files() -> list:
    root = _java_root()
    if not root.is_dir():
        return []
    return [f for f in root.rglob("java") if f.is_file() and f.parent.name == "bin"]


def find_java() -> str | None:
    for found in _java_files():
        if os.access(found, os.X_OK):
            return str(found)
    return None


def in_use_game_version():
    """The build id of the game Play would start (None when unknown)."""
    try:
        from .games import installed_builds
        return next((b.get("version") for b in installed_builds(with_size=False) if b.get("in_use")), None)
    except Exception:
        return None


def jar_ok(path=None) -> bool:
    path = Path(path or JAR)
    return path.is_file() and zipfile.is_zipfile(path)


def ready() -> bool:
    return bool(find_java()) and jar_ok()


def _safe_extract(archive: tarfile.TarFile, dest: Path) -> None:
    try:
        archive.extractall(dest, filter="data")   # refuses links and paths that escape
    except TypeError as exc:                      # Python without extraction filters
        raise BolError("This Python cannot unpack the Java runtime safely.") from exc


JAVA_RELEASES_REPO = f"adoptium/temurin{JAVA_MAJOR}-binaries"     # second source: GitHub publishes a SHA-256 per file
_JAVA_ARCHIVE = re.compile(rf"OpenJDK{JAVA_MAJOR}U-jre_x64_linux_hotspot_[\w.+\-]+\.tar\.gz")


def _checked(url: str, name: str, digest: str) -> tuple[str, str, str]:
    if (not url.startswith("https://") or not re.fullmatch(r"[\w.+\-]+\.tar\.gz", name)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise BolError("The answer for the Java runtime could not be verified, "
                       "so nothing was downloaded.")
    return url, name, digest


def _java_package() -> tuple[str, str, str]:
    """(url, file name, SHA-256) of the newest Java runtime.

    Adoptium's listing is asked up to three times (its API now and then answers
    406 or a 5xx to a perfectly good request); if it stays unreachable the same
    build is looked up in Temurin's GitHub releases, which publish a digest too.
    """
    failures: list = []
    for attempt, accept in enumerate(("application/json", "*/*", "application/json")):
        if attempt:
            time.sleep(1.5 * attempt)
        try:
            package = util.http_json(JAVA_ASSETS_URL, timeout=30, accept=accept)[0]["binary"]["package"]
            return _checked(str(package["link"]), str(package["name"]),
                            str(package.get("checksum") or "").lower())
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            failures.append(exc)
    try:
        release = util.gh_latest(JAVA_RELEASES_REPO)
        url, name, _size = util.asset_url(release, lambda n: bool(_JAVA_ARCHIVE.fullmatch(n)))
        digest = util.asset_sha256(release, name) if url else None
        if url and digest:
            return _checked(url, name, digest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failures.append(exc)
    raise BolError(f"Could not look up the Java runtime download ({failures[0]}).") from failures[0]


def _clean_runtime_leftovers(keep: str) -> None:
    """Remove what an interrupted earlier install left in RUNTIME_DIR."""
    now = time.time()
    try:
        entries = list(RUNTIME_DIR.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.name.startswith(".java-staging-"):
                if now - entry.stat().st_mtime > 3600:      # not one another window is filling
                    shutil.rmtree(entry, ignore_errors=True)
            elif entry.name.endswith((".tar.gz", ".tar.gz.part")) and not entry.name.startswith(keep):
                entry.unlink()
        except OSError:
            pass


def _java_runs(java: str) -> str | None:
    """None when `java -version` works, else why not."""
    try:
        done = subprocess.run([java, "-version"], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(getattr(exc, "strerror", None) or exc)
    if done.returncode != 0:
        return (done.stderr or done.stdout or f"exit {done.returncode}").strip()[-300:]
    return None


def ensure_java(progress=None) -> str:
    java = find_java()
    if java:
        return java
    present = _java_files()
    if present:
        # Unpacked but not runnable (an exec bit lost, or a drive mounted noexec):
        # downloading it again would give the same result on every launch.
        for f in present:
            try:
                f.chmod(f.stat().st_mode | 0o111)
            except OSError:
                pass
        java = find_java()
        if java:
            return java
        raise BolError(f"The Java runtime in {_java_root()} cannot be run (no permission to "
                       "execute it). If the Gomceix data folder is on a drive mounted without "
                       "execute permission, move it elsewhere.")
    with _LOCK:
        java = find_java()
        if java:
            return java
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        url, name, digest = _java_package()
        _clean_runtime_leftovers(name)
        archive = RUNTIME_DIR / name       # named by version: a resumed download is never mixed
        staging = Path(tempfile.mkdtemp(prefix=".java-staging-", dir=RUNTIME_DIR))
        try:
            util.download(url, archive, "Java runtime", progress)
            if util.sha256_file(archive) != digest:
                raise BolError("The downloaded Java runtime does not match the checksum "
                               "Adoptium published, so it was not installed.")
            try:
                with tarfile.open(archive) as tar:
                    _safe_extract(tar, staging)
            except BolError:
                raise
            except Exception as exc:       # corrupt archive, unsafe member, disk full
                raise BolError(f"The Java runtime could not be unpacked ({exc}).") from exc
            shutil.rmtree(_java_root(), ignore_errors=True)
            os.replace(staging, _java_root())
        except BaseException:
            # A file that failed its check must not be resumed or reused.
            if archive.exists() and util.sha256_file(archive) != digest:
                archive.unlink(missing_ok=True)
                Path(str(archive) + ".part").unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            archive.unlink(missing_ok=True)
    java = find_java()
    if not java:
        raise BolError("The downloaded Java runtime has no java program in it.")
    problem = _java_runs(java)
    if problem:
        shutil.rmtree(_java_root(), ignore_errors=True)
        raise BolError(f"The downloaded Java runtime does not start ({problem}).")
    return java


def _verified_jar_url(release) -> tuple[str, str | None]:
    """(download url, SHA-256 the release publishes for it or None)."""
    url, name, _size = util.asset_url(release, lambda n: n.endswith(".jar"))
    if not url:
        raise BolError("The ProxyPass download has no .jar file.")
    return url, util.asset_sha256(release, name)


# ------------------------------------------------- one build per game version
# ProxyPass speaks exactly one Bedrock protocol, so each build only works with
# the game version it was made for. Its release notes name that version in the
# first change line ("- 1.26.30 ..."); builds without such a line are fixes
# for an earlier one and are not offered.
_BODY_VERSION = re.compile(r"^\s*-\s*v?(\d+\.\d+\.\d+)\b", re.M)
_TAG_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def game_key(tag) -> str | None:
    """'1.26.30.2' (a game build id) -> '1.26.30'; None when it is not a version."""
    m = _TAG_VERSION.match(str(tag or "").strip())
    return ".".join(m.groups()) if m else None


def _version_tuple(version: str):
    return tuple(int(x) for x in version.split("."))


def builds(ignore_cache: bool = False) -> dict:
    """{game version: newest stable ProxyPass release made for it} (empty when offline and uncached)."""
    try:
        releases = util.gh_releases(JAR_REPO, per_page=100, ignore_cache=ignore_cache) or []
    except Exception:
        return {}
    found: dict = {}
    for release in releases:                          # newest first
        tag = str(release.get("tag_name") or "")
        if not tag.startswith("master-") or release.get("draft") or release.get("prerelease"):
            continue
        m = _BODY_VERSION.search(release.get("body") or "")
        if m:
            found.setdefault(m.group(1), release)
    return found


def supported_versions(ignore_cache: bool = False) -> list:
    """Game versions with a ProxyPass build, newest first."""
    return sorted(builds(ignore_cache), key=_version_tuple, reverse=True)


def jar_path(version: str) -> Path:
    return PROXY_DIR / f"ProxyPass-{version}.jar"


def _all_jars() -> list:
    return [p for p in (JAR, *sorted(PROXY_DIR.glob("ProxyPass-*.jar"))) if jar_ok(p)]


def any_jar() -> bool:
    return bool(_all_jars())


def support_problem(tag, known=None) -> str | None:
    """Why ProxyPass cannot play game build `tag`, or None (supported, or not known)."""
    key = game_key(tag)
    known = builds() if known is None else known
    if key is None or not known or key in known or jar_ok(jar_path(key)):
        return None
    listed = ", ".join(v[2:] if v.startswith("1.") else v
                       for v in sorted(known, key=_version_tuple, reverse=True)[:6])
    return _("ProxyPass has no build for Minecraft {version}. It works with: {listed}. "
             "Pick one of those versions, or use Normal mode.", version=key[2:], listed=listed)


def starts_without_proxy(tag) -> bool:
    """Online mode off lets every version be played; one with no build has no proxy to run."""
    return not online_mode() and support_problem(tag) is not None


def _download_jar(release, dest: Path, progress) -> None:
    url, expected = _verified_jar_url(release)
    if expected is None and not (
            util.env_flag(util.load_settings().get("allow_unpinned_proxypass"))
            or util.env_flag(os.environ.get("GOMCEIX_ALLOW_UNPINNED_PROXYPASS"))):
        raise BolError("This ProxyPass release publishes no SHA-256 for its jar, so it was "
                       "not downloaded: it could not be verified. Set "
                       "allow_unpinned_proxypass in the settings to accept it anyway.")
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".new")
    part.unlink(missing_ok=True)
    Path(str(part) + ".part").unlink(missing_ok=True)
    try:
        util.download(url, part, "ProxyPass", progress)
        if expected and util.sha256_file(part) != expected:
            raise BolError("The downloaded ProxyPass file does not match the checksum "
                           "published for its release, so it was not installed.")
        if not zipfile.is_zipfile(part):
            raise BolError("The downloaded ProxyPass file is not a valid jar.")
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)


def ensure_jar(progress=None, version=None) -> str:
    """The jar to run. With `version` (a game build id) it is the build made for that
    game version; without, any jar that is already here, else the newest one."""
    key = game_key(version)
    if key:
        target = jar_path(key)
        if jar_ok(target):
            return str(target)
        with _LOCK:
            if jar_ok(target):
                return str(target)
            known = builds()
            problem = support_problem(key, known)
            if problem:
                raise BolError(problem)
            if key not in known:
                raise BolError("The list of ProxyPass builds could not be loaded. Check the "
                               "connection and try again.")
            _download_jar(known[key], target, progress)
        return str(target)
    have = _all_jars()
    if have:
        return str(have[-1] if have[0] == JAR and len(have) > 1 else have[0])
    with _LOCK:
        return _ensure_latest_jar(progress)


def _ensure_latest_jar(progress=None) -> str:
    if jar_ok():
        return str(JAR)
    # The release is "latest": a half-finished file of an older one must not be resumed.
    _download_jar(util.gh_latest(JAR_REPO), JAR, progress)
    return str(JAR)


def ensure_components(progress=None, version=None) -> tuple[str, str]:
    """(java, jar), downloading whichever is missing; `version` picks the jar made for that game version."""
    return ensure_java(progress), ensure_jar(progress, version)


# --------------------------------------------------------- server address
_KEY = re.compile(r"^(\s*)(host|port)\s*:\s*(.*?)\s*(#.*)?$")
_LOOPBACK = re.compile(r"^(localhost|127(\.\d{1,3}){3}|::1|\[::1\])$", re.I)


# Servers offered by name. The Hive's Bedrock address is "geo." (its Java one is play.hivemc.com).
SERVER_PRESETS = (
    ("hive", "Hive", "geo.hivebedrock.network", "19132"),
)
DEFAULT_SERVER = SERVER_PRESETS[0]


def preset_for(host, port) -> str | None:
    """The id of the preset that is exactly host:port, else None."""
    for pid, _name, phost, pport in SERVER_PRESETS:
        if str(host).strip().lower() == phost and str(port).strip() == pport:
            return pid
    return None


# Listens on this computer only: nobody else on the network can use the proxy.
_TEMPLATE = ("# ProxyPass configuration (written by Gomceix)", "proxy:", "  host: 127.0.0.1",
             f"  port: {LISTEN_PORT}", "destination:", f"  host: {DEFAULT_SERVER[2]}",
             f"  port: {DEFAULT_SERVER[3]}",
             "online-mode: true", "save-auth-details: true", "broadcast-session: false", "max-clients: 0")


_ONLINE_KEY = "online-mode"


def config_path() -> Path:
    return PROXY_DIR / "config.yml"


def _top_level(line: str) -> bool:
    """A line that starts a top-level key (not blank, indented or a comment)."""
    return bool(line.strip()) and not line.startswith((" ", "\t", "#"))


def _key_name(line: str) -> str:
    return line.split(":", 1)[0].strip().strip("\"'")


def _read_lines() -> list | None:
    try:
        # utf-8-sig: a byte-order mark would otherwise hide the first key.
        return config_path().read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None


def _read_block(block: str) -> dict:
    """The host/port values under a top-level key of config.yml ({} when absent)."""
    found: dict = {}
    current = child = None
    for line in _read_lines() or ():
        if _top_level(line):
            current, child = _key_name(line), None
            inline = line.split(":", 1)[1] if ":" in line else ""
            if current == block and "{" in inline:       # destination: {host: a, port: 1}
                for key, value in re.findall(r"\b(host|port)\s*:\s*([^,}\s]+)", inline):
                    found[key] = value.strip("\"'")
            continue
        if current != block or not line.strip() or line.lstrip().startswith("#"):
            continue
        child = line[:len(line) - len(line.lstrip())] if child is None else child
        m = _KEY.match(line)
        if m and m.group(1) == child:        # not a host/port of something nested deeper
            value = m.group(3).strip("\"'")
            if value:
                found[m.group(2)] = value
    return found


def _points_at_itself(host, port) -> bool:
    """A destination that is the proxy's own address: it would only forward to itself."""
    return bool(_LOOPBACK.match(str(host).strip())) and str(port).strip() == listen_port()


def read_destination() -> tuple[str, str]:
    """(host, port) of the server ProxyPass forwards to.

    Before the first run, or while it still points at the proxy's own address (what
    an older config held), that is the default server rather than a loop."""
    found = _read_block("destination")
    host, port = found.get("host"), found.get("port")
    if not host or not port or _points_at_itself(host, port):
        return DEFAULT_SERVER[2], DEFAULT_SERVER[3]
    return host, port


def ensure_destination() -> None:
    """Put a usable server in config.yml when it holds none or only the proxy's own address."""
    lines = _read_lines()
    if lines is None:
        return                                   # ensure_local_listen writes the whole template
    found = _read_block("destination")
    if not found.get("host") or not found.get("port") or _points_at_itself(found["host"], found["port"]):
        _write_config(_set_keys(lines, "destination", {"host": DEFAULT_SERVER[2], "port": DEFAULT_SERVER[3]}))


def listen_port() -> str:
    """The port ProxyPass listens on (its own config wins over the default)."""
    port = _read_block("proxy").get("port", LISTEN_PORT)
    return port if valid_port(port) else LISTEN_PORT


def valid_host(host: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?", host or ""))


def valid_port(port) -> bool:
    return str(port).isdigit() and 1 <= int(port) <= 65535


def _set_keys(lines: list, block: str, values: dict) -> list:
    """`lines` with host/port under top-level `block` set from `values`.

    Everything else is kept. Keys the block lacks are added (a missing block is
    appended), and an inline `block: {...}` is turned into a block, since lines
    added under it would not be valid YAML.
    """
    out, current, seen, at, indent = [], None, set(), None, None
    child = None
    for line in lines:
        if _top_level(line):
            current, child = _key_name(line), None
            if current == block:
                head = line.split(":", 1)[1].split("#")[0].strip() if ":" in line else ""
                if head:
                    line = f"{block}:"          # inline value: replaced by the block below
                if at is None:
                    at = len(out)
        else:
            m = _KEY.match(line)
            if current == block and line.strip() and not line.lstrip().startswith("#"):
                child = line[:len(line) - len(line.lstrip())] if child is None else child
            if current == block and m and m.group(1) == child:
                indent = m.group(1) if indent is None else indent
                key = m.group(2)
                if key in values:
                    value = values[key]
                    out.append(f"{m.group(1)}{key}: {value}")
                    seen.add(key)
                    continue
        out.append(line)
    missing = [k for k in ("host", "port") if k in values and k not in seen]
    if at is None:
        out += [f"{block}:", *[f"  {k}: {values[k]}" for k in missing]]
    elif missing:
        pad = indent if indent is not None else "  "
        out[at + 1:at + 1] = [f"{pad}{k}: {values[k]}" for k in missing]
    return out


def _write_config(lines: list) -> None:
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PROXY_DIR, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, config_path())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_destination(host: str, port) -> None:
    """Point ProxyPass at host:port, keeping every other line of its config."""
    if not valid_host(host):
        raise BolError(f"'{host}' is not a valid server address.")
    if not valid_port(port):
        raise BolError(f"'{port}' is not a valid port (1-65535).")
    lines = _read_lines()
    if lines is None:
        lines = list(_TEMPLATE)     # a complete file, so none of ProxyPass's own defaults is lost
    # The host is quoted so YAML cannot read "1234", "yes" or "1e3" as anything but text.
    _write_config(_set_keys(lines, "destination", {"host": f'"{host}"', "port": int(port)}))


def ensure_local_listen() -> None:
    """Make sure the proxy accepts connections from this computer only.

    ProxyPass's own default config listens on 0.0.0.0, which would let anyone on
    the network join servers as the signed-in player. A missing config is written
    from the template; a non-loopback listen address is put back to 127.0.0.1.
    """
    lines = _read_lines()
    if lines is None:
        _write_config(list(_TEMPLATE))
        return
    host = _read_block("proxy").get("host")
    if host is None or not _LOOPBACK.match(host):
        warn(f"ProxyPass was set to listen on {host or 'every address'}; Gomceix keeps it on "
             "127.0.0.1 so nobody else on the network can play as you.")
        _write_config(_set_keys(lines, "proxy", {"host": "127.0.0.1"}))


def _online_mode_lines(lines: list) -> list:
    """The `online-mode` lines of the config: top-level ones, whatever their spacing."""
    return [line for line in lines if _top_level(line) and _key_name(line) == _ONLINE_KEY]


def online_mode() -> bool:
    """Whether ProxyPass signs in with Microsoft. Only a clear "off" in config.yml turns it
    off, since a server that checks accounts refuses a player without one."""
    found = _online_mode_lines(_read_lines() or ())
    if not found:
        return True
    value = found[0].split(":", 1)[1].split("#")[0].strip().strip("\"'").lower() if ":" in found[0] else ""
    return value not in ("false", "no", "off")


def write_online_mode(enabled: bool) -> None:
    """Set online-mode, keeping every other line of the config. A saved account stays."""
    wanted = f"{_ONLINE_KEY}: {'true' if enabled else 'false'}"
    lines = _read_lines()
    if lines is None:
        lines = list(_TEMPLATE)
    if _online_mode_lines(lines):
        lines = [wanted if _top_level(line) and _key_name(line) == _ONLINE_KEY else line for line in lines]
    else:
        lines.append(wanted)
    _write_config(lines)


def ensure_online_mode() -> None:
    """Spell out online-mode when the config lacks it: online_mode() and ProxyPass must agree."""
    lines = _read_lines()
    if lines is not None and not _online_mode_lines(lines):
        write_online_mode(True)


def port_problem(port=None) -> str | None:
    """Why the proxy cannot listen on its port right now, or None."""
    port = int(port or listen_port())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)       # Bedrock speaks UDP
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            return (f"Port {port} is already in use: another ProxyPass, a Minecraft world open "
                    "to the network or a server is listening on it. Close it and try again.")
        if exc.errno == errno.EACCES:
            return f"This account may not listen on port {port}."
        return None          # anything else is not a port conflict; ProxyPass will report it
    finally:
        sock.close()
    return None


# ------------------------------------------------------------ the process
_LINK = re.compile(r"(https?://(?:www\.)?microsoft\.com/link\S*)")
_CODE = re.compile(r"\b([A-Z0-9]{8,9})\b")


def parse_device_code(line: str):
    """(url, code) when a ProxyPass log line carries the Microsoft sign-in code."""
    url = _LINK.search(line)
    if url and "code" in line.lower():
        code = _CODE.search(line[url.end():]) or _CODE.search(line)
        if code:
            return url.group(1), code.group(1)
    return None


# Newer ProxyPass builds print the link and the code on two separate lines:
#   Go to https://www.microsoft.com/link
#   Enter code 59EW7MQL
_CODE_LINE = re.compile(r"(?i:enter\s+(?:the\s+)?code)[:\s]+([A-Z0-9]{8,9})\b")
DEFAULT_LINK = "https://www.microsoft.com/link"


class DeviceCodeParser:
    """Finds the sign-in code in ProxyPass's output, whether the link and the code share a
    line (older builds) or come on two (newer ones). Feed it one line at a time."""

    def __init__(self):
        self.url = None

    def feed(self, line: str):
        link = _LINK.search(line)
        if link:
            self.url = link.group(1).rstrip(".,;)")
        both = parse_device_code(line)
        if both:
            return both
        code = _CODE_LINE.search(line)
        if code:
            return (self.url or DEFAULT_LINK, code.group(1))
        return None


def _auth_file() -> Path:
    return PROXY_DIR / "auth.json"


def signed_in() -> bool:
    """True when ProxyPass has saved a complete account file.

    Existing is not enough: ProxyPass may be mid-write, and an empty or cut-off
    file is no account.
    """
    try:
        return isinstance(json.loads(_auth_file().read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def sign_out() -> bool:
    try:
        _auth_file().unlink()
        return True
    except OSError:
        return False


def session_running() -> bool:
    """Whether a ProxyPass this launcher started is still up."""
    return any(session.alive() for session in list(_SESSIONS))


# A ProxyPass that outlived the launcher (killed, crashed) would keep the port
# and the account's session. Its pid is written down with the launcher's, and
# the next start closes it once that launcher is gone.
def _pid_file() -> Path:
    return PROXY_DIR / "proxypass.pid"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _is_our_jar(arg: bytes) -> bool:
    """A jar this launcher starts: the unversioned one or a per-version build."""
    path = Path(os.fsdecode(arg))
    return path == JAR or (path.parent == PROXY_DIR and path.match("ProxyPass-*.jar"))


def _is_our_proxy(pid: int) -> bool:
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if b"-jar" not in cmd:
            return False
        jar = cmd[cmd.index(b"-jar") + 1:][:1]
        return bool(jar) and _is_our_jar(jar[0]) and os.getpgid(pid) == pid
    except (OSError, ValueError):
        return False


def _reap_stale() -> None:
    try:
        java_pid, owner = (int(x) for x in _pid_file().read_text().split()[:2])
    except (OSError, ValueError):
        _pid_file().unlink(missing_ok=True)
        return
    if owner == os.getpid() or _pid_alive(owner):
        return                   # its launcher is still around: not ours to close
    if _is_our_proxy(java_pid):
        info("Closing a ProxyPass left behind by an earlier session.")
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(java_pid, sig)
            except OSError:
                break
            deadline = time.monotonic() + STOP_GRACE_S
            while time.monotonic() < deadline and _pid_alive(java_pid):
                time.sleep(0.1)
            if not _pid_alive(java_pid):
                break
    _pid_file().unlink(missing_ok=True)


def _prune_sessions(keep: int = SESSIONS_KEPT) -> None:
    """Remove all but the newest `keep` of ProxyPass's own per-session folders.
    Only called while no ProxyPass of ours is up, so none of them is in use."""
    root = PROXY_DIR / "sessions"
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
        folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in folders[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def _stop_all() -> None:
    for session in list(_SESSIONS):
        try:
            session.stop()
        except Exception:
            pass


atexit.register(_stop_all)


class ProxySession:
    """One running ProxyPass. `start()` returns once it has survived its first moments;
    `stop()` is safe to repeat."""

    def __init__(self, on_line=None, version=None):
        self.on_line = on_line
        self.version = version        # game build id: picks the jar made for it
        self.proc: subprocess.Popen | None = None
        self._stop_lock = threading.Lock()

    def start(self) -> None:
        java, jar = ensure_components(version=self.version)
        PROXY_DIR.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        _reap_stale()
        ensure_local_listen()
        ensure_destination()
        ensure_online_mode()
        port = listen_port()
        problem = port_problem(port)
        if problem:
            raise BolError(problem)
        _prune_sessions()
        try:
            proc = subprocess.Popen(
                [java, *_JAVA_FLAGS, "-jar", jar], cwd=str(PROXY_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True)
        except OSError as exc:
            raise BolError(f"Java could not be started ({exc.strerror or exc}). Remove the "
                           "Java component and install it again.") from exc
        self.proc = proc
        _SESSIONS.add(self)
        try:
            _pid_file().write_text(f"{proc.pid} {os.getpid()}\n")
        except OSError:
            pass
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        deadline = time.monotonic() + STARTUP_CHECK_S
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.1)
        if proc.poll() is not None:
            self.stop()
            raise BolError(f"ProxyPass stopped right after it started (exit {proc.returncode}). "
                           f"See {LOGS / 'proxypass.log'}.")
        info(f"ProxyPass is listening on 127.0.0.1:{port}.")

    def _pump(self, proc) -> None:
        log = None
        try:
            log_path = LOGS / "proxypass.log"
            try:
                if log_path.stat().st_size > _LOG_CAP:
                    os.replace(log_path, log_path.with_suffix(".log.1"))
            except OSError:
                pass
            try:
                log = open(log_path, "ab")
            except OSError as exc:
                warn(f"ProxyPass log not kept ({exc.strerror or exc}).")
            # Keep reading even when the log cannot be written: a pipe nobody
            # empties would stop Java, and the sign-in code arrives on it.
            for raw in iter(proc.stdout.readline, b""):
                if log is not None:
                    try:
                        log.write(raw)
                        log.flush()
                    except OSError:
                        log = None
                if self.on_line:
                    try:
                        self.on_line(raw.decode(errors="replace"))
                    except Exception:
                        pass
        except (OSError, ValueError):
            pass
        finally:
            if log is not None:
                log.close()
            try:
                proc.stdout.close()
            except OSError:
                pass

    def alive(self) -> bool:
        return bool(self.proc) and self.proc.poll() is None

    def stop(self) -> None:
        """End ProxyPass and everything it started (its own process group)."""
        with self._stop_lock:
            proc = self.proc
            if proc is None:
                return
            if proc.poll() is None:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        # Only ever the group made for it: never the launcher's own.
                        if os.getpgid(proc.pid) == proc.pid:
                            os.killpg(proc.pid, sig)
                        elif sig == signal.SIGTERM:
                            proc.terminate()
                        else:
                            proc.kill()
                    except OSError:
                        pass
                    try:
                        proc.wait(timeout=STOP_GRACE_S)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            try:
                owner = _pid_file().read_text().split()
                if owner and owner[0] == str(proc.pid):
                    _pid_file().unlink()
            except (OSError, ValueError):
                pass


class ProxyLogin:
    """Sign in to Microsoft through ProxyPass; same shape as the native device-code login.

    Runs the proxy until it saves its account file, passing the sign-in code on to the window.
    """
    TIMEOUT_S = 15 * 60

    def __init__(self):
        self._stop = threading.Event()
        self._session: ProxySession | None = None

    def start(self, on_auth, on_online, on_error=None):
        if signed_in():
            # Already linked: nothing to sign in to (and no process to start).
            on_online()
            return

        def work():
            sent = {"code": None}
            parser = DeviceCodeParser()

            def line(text):
                found = parser.feed(text)
                if found and found[1] != sent["code"]:
                    sent["code"] = found[1]
                    on_auth(*found)

            session = ProxySession(on_line=line)
            self._session = session
            timed_out = False
            try:
                session.start()
                deadline = time.monotonic() + self.TIMEOUT_S
                while not self._stop.is_set():
                    if signed_in():
                        # ProxyPass may still be finishing the file: stopping it mid-write
                        # would cut the account off, so see it settle first.
                        time.sleep(1.0)
                        if signed_in():
                            break
                    if not session.alive():
                        raise BolError("ProxyPass stopped before the sign-in finished. "
                                       f"See {LOGS / 'proxypass.log'}.")
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    time.sleep(0.5)
            except Exception as exc:
                session.stop()
                if on_error and not self._stop.is_set():
                    on_error(str(exc) or type(exc).__name__)
                return
            session.stop()
            if self._stop.is_set():
                return
            if timed_out:
                if on_error:
                    on_error("The sign-in was not finished in time. Click Sign in to try again.")
            elif signed_in():
                on_online()

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self._stop.set()
        session = self._session
        if session:
            session.stop()
