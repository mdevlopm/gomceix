"""Audit regressions for ProxyPass mode: config edits, port, process group, downloads, sign-in."""
import hashlib
import io
import os
import signal
import socket
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import pytest

from gomceix.core import proxypass as pp
from gomceix.core import util
from gomceix.core.log import BolError


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PROXY_DIR", tmp_path / "proxypass")
    monkeypatch.setattr(pp, "JAR", tmp_path / "proxypass" / "ProxyPass.jar")
    monkeypatch.setattr(pp, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(pp, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(pp, "STOP_GRACE_S", 3.0)
    monkeypatch.setattr(pp, "STARTUP_CHECK_S", 0.3)
    monkeypatch.setattr(util, "load_settings", lambda: {})
    monkeypatch.delenv("GOMCEIX_ALLOW_UNPINNED_PROXYPASS", raising=False)
    return tmp_path


def _write(env, text, name="config.yml"):
    d = env / "proxypass"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(text if isinstance(text, bytes) else text.encode())


def _cfg(env):
    return (env / "proxypass" / "config.yml").read_text()


# ------------------------------------------------------------ config edits
def test_crlf_config_is_rewritten_and_still_readable(env):
    _write(env, "proxy:\r\n  host: 127.0.0.1\r\n  port: 19132\r\ndestination:\r\n  host: a\r\n  port: 1\r\nx: 1")
    pp.write_destination("b.example", 2)
    assert pp.read_destination() == ("b.example", "2")
    assert "\r" not in _cfg(env) and _cfg(env).endswith("x: 1\n")


def test_quoted_values_and_comments_are_replaced_cleanly(env):
    _write(env, 'destination:\n  host: "old.example"  # c\n  port: \'25565\'\n')
    pp.write_destination("new.example", 19133)
    assert pp.read_destination() == ("new.example", "19133")


def test_numeric_looking_host_is_written_as_text(env):
    pp.write_destination("1234", 19132)
    assert 'host: "1234"' in _cfg(env) and pp.read_destination() == ("1234", "19132")


def test_duplicate_keys_are_all_updated_and_nothing_is_added(env):
    _write(env, "destination:\n  host: a\n  host: b\n  port: 1\n")
    pp.write_destination("c.example", 3)
    assert _cfg(env).count("c.example") == 2 and _cfg(env).count("port: 3") == 1


def test_missing_trailing_newline_and_bom(env):
    _write(env, b"\xef\xbb\xbfproxy:\n  host: 0.0.0.0\ndestination:\n  host: a\n  port: 1")
    assert pp._read_block("proxy") == {"host": "0.0.0.0"}
    pp.write_destination("z.example", 9)
    assert pp.read_destination() == ("z.example", "9")


def test_inline_flow_destination_stays_valid_yaml(env):
    _write(env, "destination: {host: a.example, port: 5}\nonline-mode: true\n")
    assert pp.read_destination() == ("a.example", "5")
    pp.write_destination("b.example", 6)
    text = _cfg(env)
    assert "{" not in text and text.startswith("destination:\n")
    assert pp.read_destination() == ("b.example", "6") and "online-mode: true" in text


def test_destination_block_missing_a_key_gets_it_with_the_same_indent(env):
    _write(env, "destination:\n    host: a\nother: 1\n")
    pp.write_destination("b.example", 7)
    assert '    port: 7' in _cfg(env) and pp.read_destination() == ("b.example", "7")


def test_nested_or_similarly_named_keys_are_left_alone(env):
    _write(env, "destination:\n  host: a\n  port: 1\n  extra:\n    host: keep\n    port: keep\n"
                "destination-old:\n  host: stay\n  port: stay\n")
    pp.write_destination("b.example", 2)
    text = _cfg(env)
    assert "    host: keep" in text and "host: stay" in text and "port: stay" in text


# ------------------------------------------------------- local listen / port
def test_missing_config_is_written_loopback_only(env):
    pp.ensure_local_listen()
    assert pp._read_block("proxy") == {"host": "127.0.0.1", "port": "19132"}


def test_a_world_readable_listen_address_is_put_back_to_loopback(env):
    _write(env, "proxy:\n  host: 0.0.0.0\n  port: 19140\ndestination:\n  host: a\n  port: 1\n")
    pp.ensure_local_listen()
    assert pp._read_block("proxy") == {"host": "127.0.0.1", "port": "19140"}
    assert pp.read_destination() == ("a", "1")


def test_a_config_without_a_listen_host_gets_one(env):
    _write(env, "proxy:\n  port: 19140\n")
    pp.ensure_local_listen()
    assert pp._read_block("proxy")["host"] == "127.0.0.1"


def test_loopback_config_is_not_rewritten(env):
    _write(env, "proxy:\n  host: localhost\n  port: 19140\n")
    before = (env / "proxypass" / "config.yml").stat().st_mtime_ns
    pp.ensure_local_listen()
    assert (env / "proxypass" / "config.yml").stat().st_mtime_ns == before


def _udp_holder():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def test_port_in_use_is_reported_not_hung():
    holder, port = _udp_holder()
    try:
        assert "already in use" in pp.port_problem(port)
    finally:
        holder.close()
    assert pp.port_problem(port) is None


def test_start_refuses_when_the_port_is_taken_and_starts_nothing(env, monkeypatch):
    holder, port = _udp_holder()
    _write(env, f"proxy:\n  host: 127.0.0.1\n  port: {port}\n")
    monkeypatch.setattr(pp, "ensure_components", lambda **kw: ("/nonexistent/java", "j.jar"))
    spawned = []
    monkeypatch.setattr(pp.subprocess, "Popen", lambda *a, **k: spawned.append(1))
    try:
        with pytest.raises(BolError, match="already in use"):
            pp.ProxySession().start()
    finally:
        holder.close()
    assert spawned == []


# ------------------------------------------------------------- the process
def _fake_java(env, body):
    java = env / "fakejava"
    java.write_text("#!/bin/sh\n" + body)
    java.chmod(0o755)
    return java


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[1].split()[0] == "Z"
    except OSError:
        return True


def _wait(cond, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _use(env, monkeypatch, java):
    _write(env, "proxy:\n  host: 127.0.0.1\n  port: %d\n" % _udp_holder_port())
    monkeypatch.setattr(pp, "ensure_components", lambda **kw: (str(java), "j.jar"))


def _udp_holder_port():
    s, port = _udp_holder()
    s.close()
    return port


def test_stop_ends_the_whole_process_group(env, monkeypatch):
    child = env / "child.pid"
    java = _fake_java(env, f'sleep 300 &\necho $! > "{child}"\nwait\n')
    _use(env, monkeypatch, java)
    session = pp.ProxySession()
    session.start()
    assert session.alive()
    assert _wait(child.exists)
    grandchild = int(child.read_text())
    assert (env / "proxypass" / "proxypass.pid").is_file()
    session.stop()
    assert not session.alive()
    assert _wait(lambda: _gone(grandchild)), "a process of the group outlived stop()"
    assert not (env / "proxypass" / "proxypass.pid").exists()
    session.stop()                                  # safe to repeat


def test_starting_prunes_the_session_folders_of_earlier_runs(env, monkeypatch):
    root = env / "proxypass" / "sessions"
    for n in range(pp.SESSIONS_KEPT + 3):
        (root / f"player-{n}").mkdir(parents=True)
        os.utime(root / f"player-{n}", (1_000_000 + n, 1_000_000 + n))
    java = _fake_java(env, "sleep 300\n")
    _use(env, monkeypatch, java)
    session = pp.ProxySession()
    session.start()
    session.stop()
    assert len(list(root.iterdir())) == pp.SESSIONS_KEPT


def test_an_instant_crash_is_reported_with_the_log_location(env, monkeypatch):
    java = _fake_java(env, "echo 'Address already in use'\nexit 3\n")
    _use(env, monkeypatch, java)
    with pytest.raises(BolError, match="stopped right after it started"):
        pp.ProxySession().start()
    assert not (env / "proxypass" / "proxypass.pid").exists()


def test_a_java_that_cannot_be_executed_is_a_clear_error(env, monkeypatch):
    java = env / "fakejava"
    java.write_text("#!/bin/sh\n")                  # no exec bit
    _use(env, monkeypatch, java)
    with pytest.raises(BolError, match="Java could not be started"):
        pp.ProxySession().start()


def test_output_still_reaches_the_window_when_the_log_cannot_be_written(env, monkeypatch):
    java = _fake_java(env, "echo 'enter the code ABCD1234 at https://www.microsoft.com/link'\nsleep 30\n")
    _use(env, monkeypatch, java)
    (env / "logs").write_text("a file where the log folder should be")
    monkeypatch.setattr(pp, "LOGS", env / "logs" / "sub")
    seen = []
    session = pp.ProxySession(on_line=seen.append)
    # LOGS.mkdir fails in start(); drive the pump directly the way start() does.
    proc = subprocess.Popen([str(java)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    session.proc = proc
    t = threading.Thread(target=session._pump, args=(proc,), daemon=True)
    t.start()
    assert _wait(lambda: any("ABCD1234" in x for x in seen))
    session.stop()
    t.join(5)


def test_a_proxy_left_by_a_dead_launcher_is_closed_at_the_next_start(env, monkeypatch):
    (env / "proxypass").mkdir()
    orphan = subprocess.Popen(["sh", "-c", "sleep 300; true", "-jar", str(pp.JAR)],
                              start_new_session=True)
    try:
        (env / "proxypass" / "proxypass.pid").write_text(f"{orphan.pid} 2147483000\n")
        pp._reap_stale()
        assert _wait(lambda: orphan.poll() is not None)
        assert not (env / "proxypass" / "proxypass.pid").exists()
    finally:
        if orphan.poll() is None:
            os.killpg(orphan.pid, signal.SIGKILL)
        orphan.wait()


def test_old_session_folders_are_pruned_and_the_newest_kept(env):
    root = env / "proxypass" / "sessions"
    for n in range(14):
        folder = root / f"player-{n}"
        folder.mkdir(parents=True)
        (folder / "skinData.json").write_text("{}")
        os.utime(folder, (1_000_000 + n, 1_000_000 + n))
    (root / "notes.txt").write_text("not a session")
    pp._prune_sessions(keep=10)
    assert sorted(p.name for p in root.iterdir() if p.is_dir()) == sorted(f"player-{n}" for n in range(4, 14))
    assert (root / "notes.txt").exists()
    pp._prune_sessions(keep=10)                   # nothing to do, and no sessions folder at all is fine
    (env / "proxypass" / "sessions").rename(env / "proxypass" / "elsewhere")
    pp._prune_sessions()


def test_a_proxy_running_a_versioned_jar_is_closed_too(env):
    # Launches pass the game version, so the jar in use is ProxyPass-<version>.jar.
    (env / "proxypass").mkdir()
    orphan = subprocess.Popen(["sh", "-c", "sleep 300; true", "-jar", str(pp.jar_path("1.26.30"))],
                              start_new_session=True)
    try:
        (env / "proxypass" / "proxypass.pid").write_text(f"{orphan.pid} 2147483000\n")
        pp._reap_stale()
        assert _wait(lambda: orphan.poll() is not None)
        assert not (env / "proxypass" / "proxypass.pid").exists()
    finally:
        if orphan.poll() is None:
            os.killpg(orphan.pid, signal.SIGKILL)
        orphan.wait()


def test_a_jar_of_the_same_name_elsewhere_is_not_our_proxy(env, tmp_path):
    other = tmp_path / "ProxyPass-1.26.30.jar"
    proc = subprocess.Popen(["sh", "-c", "sleep 300; true", "-jar", str(other)], start_new_session=True)
    try:
        assert not pp._is_our_proxy(proc.pid)
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def test_a_proxy_of_a_live_launcher_or_a_stranger_is_not_touched(env):
    (env / "proxypass").mkdir()
    live = subprocess.Popen(["sh", "-c", "sleep 300; true", "-jar", str(pp.JAR)], start_new_session=True)
    stranger = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        (env / "proxypass" / "proxypass.pid").write_text(f"{live.pid} {os.getppid()}\n")
        pp._reap_stale()                              # its launcher (our parent) is alive
        assert live.poll() is None
        (env / "proxypass" / "proxypass.pid").write_text(f"{stranger.pid} 2147483000\n")
        pp._reap_stale()                              # pid reused by something else
        assert stranger.poll() is None
    finally:
        for p in (live, stranger):
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


# ------------------------------------------------------------ sign-in state
@pytest.mark.parametrize("content,expected", [("", False), ('{"tok', False), ("[1]", False),
                                               ("{}", True), ('{"a": 1}', True)])
def test_only_a_complete_account_file_counts(env, content, expected):
    _write(env, content, "auth.json")
    assert pp.signed_in() is expected


def test_login_when_already_signed_in_starts_no_process(env, monkeypatch):
    _write(env, "{}", "auth.json")
    monkeypatch.setattr(pp, "ProxySession", lambda **k: pytest.fail("must not start Java"))
    done = []
    pp.ProxyLogin().start(lambda *a: None, lambda: done.append(1))
    assert done == [1]


def test_login_timeout_is_reported_not_silent(env, monkeypatch):
    class Idle:
        def __init__(self, on_line=None): self.stopped = False
        def start(self): pass
        def alive(self): return True
        def stop(self): self.stopped = True

    monkeypatch.setattr(pp, "ProxySession", Idle)
    monkeypatch.setattr(pp.ProxyLogin, "TIMEOUT_S", 0.3)
    errors, ev = [], threading.Event()
    pp.ProxyLogin().start(lambda *a: None, lambda: errors.append("online"),
                          on_error=lambda m: (errors.append(m), ev.set()))
    assert ev.wait(5) and "not finished in time" in errors[0] and "online" not in errors


def test_login_cancel_ends_quietly(env, monkeypatch):
    stopped = threading.Event()

    class Idle:
        def __init__(self, on_line=None): pass
        def start(self): pass
        def alive(self): return True
        def stop(self): stopped.set()

    monkeypatch.setattr(pp, "ProxySession", Idle)
    called = []
    login = pp.ProxyLogin()
    login.start(lambda *a: None, lambda: called.append("online"), on_error=called.append)
    time.sleep(0.2)
    login.stop()
    assert stopped.wait(5)
    time.sleep(0.2)
    assert called == []


def test_a_half_written_account_file_is_not_taken_for_a_sign_in(env, monkeypatch):
    class Writer:
        def __init__(self, on_line=None): pass
        def start(self):
            _write(env, '{"half', "auth.json")
        def alive(self): return True
        def stop(self): pass

    monkeypatch.setattr(pp, "ProxySession", Writer)
    monkeypatch.setattr(pp.ProxyLogin, "TIMEOUT_S", 0.6)
    got = []
    ev = threading.Event()
    pp.ProxyLogin().start(lambda *a: None, lambda: got.append("online"),
                          on_error=lambda m: (got.append("error"), ev.set()))
    assert ev.wait(5) and got == ["error"]


# --------------------------------------------------------------- downloads
def _release(digest, name="ProxyPass.jar"):
    asset = {"name": name, "browser_download_url": "https://example.invalid/" + name, "size": 1}
    if digest:
        asset["digest"] = "sha256:" + digest
    return {"assets": [asset]}


def _jar_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a", "b")
    return buf.getvalue()


def _serve(monkeypatch, payload):
    def download(url, dest, label=None, progress=None, attempts=5):
        Path(dest).write_bytes(payload)
        return dest
    monkeypatch.setattr(util, "download", download)


def test_jar_is_installed_only_against_the_published_digest(env, monkeypatch):
    data = _jar_bytes()
    monkeypatch.setattr(util, "gh_latest", lambda repo: _release(hashlib.sha256(data).hexdigest()))
    _serve(monkeypatch, data)
    assert pp.ensure_jar() == str(pp.JAR) and pp.jar_ok()


def test_a_tampered_jar_is_not_installed(env, monkeypatch):
    monkeypatch.setattr(util, "gh_latest", lambda repo: _release("0" * 64))
    _serve(monkeypatch, _jar_bytes())
    with pytest.raises(BolError, match="checksum"):
        pp.ensure_jar()
    assert not pp.JAR.exists() and not list((env / "proxypass").glob("*.new*"))


def test_a_release_without_a_digest_is_refused_unless_allowed(env, monkeypatch):
    monkeypatch.setattr(util, "gh_latest", lambda repo: _release(None))
    _serve(monkeypatch, _jar_bytes())
    with pytest.raises(BolError, match="SHA-256"):
        pp.ensure_jar()
    monkeypatch.setenv("GOMCEIX_ALLOW_UNPINNED_PROXYPASS", "1")
    assert pp.ensure_jar() == str(pp.JAR)


def test_a_stale_partial_jar_download_is_not_resumed(env, monkeypatch):
    (env / "proxypass").mkdir()
    stale = env / "proxypass" / "ProxyPass.jar.new.part"
    stale.write_bytes(b"older release")
    data = _jar_bytes()
    monkeypatch.setattr(util, "gh_latest", lambda repo: _release(hashlib.sha256(data).hexdigest()))
    seen = []

    def download(url, dest, label=None, progress=None, attempts=5):
        seen.append(stale.exists())
        Path(dest).write_bytes(data)
        return dest
    monkeypatch.setattr(util, "download", download)
    pp.ensure_jar()
    assert seen == [False]


def _jre_tar(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, data, mode in members:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _java_setup(env, monkeypatch, members, digest=None):
    src = env / "src.tar.gz"
    real = _jre_tar(src, members)
    monkeypatch.setattr(pp, "_java_package", lambda: ("https://x/j.tar.gz", "j.tar.gz", digest or real))

    def download(url, dest, label=None, progress=None, attempts=5):
        Path(dest).write_bytes(src.read_bytes())
        return dest
    monkeypatch.setattr(util, "download", download)


GOOD = [("jdk/bin/java", b"#!/bin/sh\nexit 0\n", 0o755)]


def test_java_is_installed_verified_and_the_archive_removed(env, monkeypatch):
    _java_setup(env, monkeypatch, GOOD)
    java = pp.ensure_java()
    assert java == pp.find_java()
    assert not [p for p in (env / "runtime").iterdir() if p.name != "java-25"]


def test_a_java_archive_with_the_wrong_checksum_is_refused(env, monkeypatch):
    _java_setup(env, monkeypatch, GOOD, digest="1" * 64)
    with pytest.raises(BolError, match="checksum"):
        pp.ensure_java()
    assert pp.find_java() is None
    assert [p.name for p in (env / "runtime").iterdir()] == []


def test_an_archive_that_escapes_its_folder_is_refused(env, monkeypatch):
    _java_setup(env, monkeypatch, [("../evil", b"x", 0o644), *GOOD])
    with pytest.raises(BolError):
        pp.ensure_java()
    assert not (env / "evil").exists() and pp.find_java() is None
    assert [p.name for p in (env / "runtime").iterdir()] == []


def test_a_java_that_does_not_start_is_removed_and_reported(env, monkeypatch):
    _java_setup(env, monkeypatch, [("jdk/bin/java", b"#!/bin/sh\necho broken >&2\nexit 7\n", 0o755)])
    with pytest.raises(BolError, match="does not start"):
        pp.ensure_java()
    assert pp.find_java() is None


def test_an_unpacked_java_that_lost_its_exec_bit_is_repaired_not_downloaded_again(env, monkeypatch):
    java = pp._java_root() / "jdk" / "bin" / "java"
    java.parent.mkdir(parents=True)
    java.write_text("#!/bin/sh\n")
    java.chmod(0o644)
    monkeypatch.setattr(pp, "_java_package", lambda: pytest.fail("must not download"))
    assert pp.ensure_java() == str(java)


def test_stale_staging_folders_of_an_interrupted_install_are_cleaned(env, monkeypatch):
    (env / "runtime").mkdir()
    old = env / "runtime" / ".java-staging-old"
    old.mkdir()
    os.utime(old, (1, 1))
    fresh = env / "runtime" / ".java-staging-now"
    fresh.mkdir()
    (env / "runtime" / "stale.tar.gz.part").write_bytes(b"x")
    pp._clean_runtime_leftovers("j.tar.gz")
    assert not old.exists() and fresh.exists()
    assert not (env / "runtime" / "stale.tar.gz.part").exists()
