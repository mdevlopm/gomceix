"""ProxyPass mode core: server address file, sign-in code parsing, component checks."""
import pytest

from gomceix.core import proxypass as pp
from gomceix.core.log import BolError


@pytest.fixture(autouse=True)
def proxy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PROXY_DIR", tmp_path / "proxypass")
    monkeypatch.setattr(pp, "JAR", tmp_path / "proxypass" / "ProxyPass.jar")
    monkeypatch.setattr(pp, "RUNTIME_DIR", tmp_path / "runtime")
    return tmp_path / "proxypass"


def test_mode_reads_the_setting_and_defaults_to_xodus():
    assert pp.current_mode({}) == "xodus"
    assert pp.current_mode({"login_mode": "proxypass"}) == "proxypass"
    assert pp.current_mode({"login_mode": "weird"}) == "xodus"


def test_destination_defaults_before_the_first_run():
    assert pp.read_destination() == ("geo.hivebedrock.network", "19132")


def test_destination_is_written_and_everything_else_is_kept(proxy_dir):
    proxy_dir.mkdir()
    (proxy_dir / "config.yml").write_text(
        "# ProxyPass\nproxy:\n  host: 0.0.0.0\n  port: 19132\n"
        "destination:\n  host: 127.0.0.1   # old\n  port: 19133\nonline-mode: true\n")
    pp.write_destination("play.example.net", 25565)
    text = (proxy_dir / "config.yml").read_text()
    assert pp.read_destination() == ("play.example.net", "25565")
    assert "proxy:\n  host: 0.0.0.0\n  port: 19132" in text      # the listen side is untouched
    assert "# ProxyPass" in text and "online-mode: true" in text


def test_online_mode_is_written_and_everything_else_is_kept(proxy_dir):
    proxy_dir.mkdir()
    (proxy_dir / "config.yml").write_text(
        "# ProxyPass\nproxy:\n  host: 127.0.0.1\n  port: 19132\n"
        "destination:\n  host: a.example\n  port: 1234\nonline-mode: true\nmax-clients: 0\n")
    pp.write_online_mode(False)
    text = (proxy_dir / "config.yml").read_text()
    assert pp.online_mode() is False and "online-mode: false\n" in text
    assert "online-mode: true" not in text
    assert "# ProxyPass\nproxy:\n  host: 127.0.0.1" in text
    assert pp.read_destination() == ("a.example", "1234") and "max-clients: 0" in text
    pp.write_online_mode(True)
    assert pp.online_mode() is True


@pytest.mark.parametrize("line, expected", [
    ("online-mode: false", False), ("online-mode: False  # hand edit", False), ('"online-mode": "no"', False),
    ("online-mode: true", True), ("online-mode: nonsense", True), ("online-mode:", True),
    ("# online-mode: false", True), ("other:\n  online-mode: false", True),
])
def test_only_a_clear_top_level_off_counts_as_off(proxy_dir, line, expected):
    proxy_dir.mkdir()
    (proxy_dir / "config.yml").write_text(f"{line}\n")
    assert pp.online_mode() is expected


def test_online_mode_defaults_to_on_and_a_new_config_holds_the_choice(proxy_dir):
    assert pp.online_mode() is True
    pp.write_online_mode(False)
    assert pp.online_mode() is False
    assert "proxy:\n  host: 127.0.0.1\n  port: 19132" in (proxy_dir / "config.yml").read_text()


def test_a_config_without_online_mode_gets_it_spelled_out(proxy_dir):
    proxy_dir.mkdir()
    (proxy_dir / "config.yml").write_text("proxy:\n  host: 127.0.0.1\n")
    pp.ensure_online_mode()
    assert "online-mode: true\n" in (proxy_dir / "config.yml").read_text()
    pp.write_online_mode(False)
    pp.ensure_online_mode()                                      # a choice already made stays
    assert pp.online_mode() is False


def test_only_online_mode_off_starts_a_version_without_a_build(proxy_dir, monkeypatch):
    monkeypatch.setattr(pp, "builds", lambda *a, **k: {"1.26.0": {}})
    assert pp.starts_without_proxy("1.20.1.1") is False          # on: the game must not start unprotected
    pp.write_online_mode(False)
    assert pp.starts_without_proxy("1.20.1.1") is True
    assert pp.starts_without_proxy("1.26.0.2") is False          # a build exists: the proxy still runs


def test_turning_online_mode_off_keeps_the_saved_account(proxy_dir):
    proxy_dir.mkdir()
    (proxy_dir / "auth.json").write_text("{}")
    pp.write_online_mode(False)
    assert pp.signed_in()


def test_destination_is_created_when_the_file_does_not_exist(proxy_dir):
    pp.write_destination("a.example", "1234")
    assert pp.read_destination() == ("a.example", "1234")
    text = (proxy_dir / "config.yml").read_text()
    assert "proxy:\n  host: 127.0.0.1\n  port: 19132" in text      # local only
    assert "online-mode: true" in text


@pytest.mark.parametrize("host,port", [("bad host", "1"), ("a;b", "1"), ("", "1"),
                                         ("ok.example", "0"), ("ok.example", "70000"), ("ok.example", "x")])
def test_bad_addresses_are_refused_and_nothing_is_written(host, port, proxy_dir):
    with pytest.raises(BolError):
        pp.write_destination(host, port)
    assert not (proxy_dir / "config.yml").exists()


def test_device_code_is_found_in_the_proxypass_log_line():
    line = ("To sign in, use a web browser to open the page https://www.microsoft.com/link "
            "and enter the code ABCD1234 to authenticate.")
    assert pp.parse_device_code(line) == ("https://www.microsoft.com/link", "ABCD1234")
    assert pp.parse_device_code("[INFO] Proxy started on 0.0.0.0:19132") is None


def test_ready_needs_java_and_a_real_jar(proxy_dir, tmp_path):
    assert not pp.ready()
    proxy_dir.mkdir()
    (proxy_dir / "ProxyPass.jar").write_bytes(b"not a zip")
    assert not pp.jar_ok()
    import zipfile
    with zipfile.ZipFile(proxy_dir / "ProxyPass.jar", "w") as z:
        z.writestr("a", "b")
    assert pp.jar_ok() and not pp.ready()
    java = pp._java_root() / "jdk" / "bin" / "java"
    java.parent.mkdir(parents=True)
    java.write_text("#!/bin/sh\n")
    java.chmod(0o755)
    assert pp.find_java() == str(java) and pp.ready()


def test_sign_in_state_follows_the_account_file(proxy_dir):
    assert not pp.signed_in()
    proxy_dir.mkdir()
    (proxy_dir / "auth.json").write_text("{}")
    assert pp.signed_in() and pp.sign_out() and not pp.signed_in()


def test_login_passes_the_code_on_and_finishes_when_the_account_file_appears(proxy_dir, monkeypatch):
    import threading

    class FakeSession:
        def __init__(self, on_line=None):
            self.on_line, self.stopped = on_line, False

        def start(self):
            proxy_dir.mkdir(parents=True, exist_ok=True)
            self.on_line("To sign in open https://www.microsoft.com/link and enter the code ZXCV5678")
            (proxy_dir / "auth.json").write_text("{}")

        def alive(self):
            return True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(pp, "ProxySession", FakeSession)
    got, done = [], threading.Event()
    pp.ProxyLogin().start(lambda url, code: got.append((url, code)), done.set)
    assert done.wait(5) and got == [("https://www.microsoft.com/link", "ZXCV5678")]


def test_login_reports_a_proxy_that_dies_early(monkeypatch):
    import threading

    class DeadSession:
        def __init__(self, on_line=None): pass
        def start(self): pass
        def alive(self): return False
        def stop(self): pass

    monkeypatch.setattr(pp, "ProxySession", DeadSession)
    errors, ev = [], threading.Event()
    pp.ProxyLogin().start(lambda *a: None, lambda: errors.append("online"),
                          on_error=lambda m: (errors.append(m), ev.set()))
    assert ev.wait(5) and "stopped before the sign-in finished" in errors[0]


def test_the_code_is_found_when_the_link_and_the_code_are_on_separate_lines():
    """The real ProxyPass output of build 67 (the sign-in dialog never opened because of this)."""
    parser = pp.DeviceCodeParser()
    lines = ["[23:18:18 INFO ]: Online mode is enabled. Starting auth process...",
             "[23:18:18 INFO ]: Go to https://www.microsoft.com/link",
             "[23:18:18 INFO ]: Enter code 59EW7MQL",
             "[23:18:19 INFO ]: Copied code to clipboard"]
    found = [parser.feed(line) for line in lines]
    assert found == [None, None, ("https://www.microsoft.com/link", "59EW7MQL"), None]


def test_the_older_one_line_format_still_works_and_a_missing_link_falls_back():
    assert pp.DeviceCodeParser().feed(
        "To sign in, use a web browser to open the page https://www.microsoft.com/link and enter the code ABCD1234"
    ) == ("https://www.microsoft.com/link", "ABCD1234")
    assert pp.DeviceCodeParser().feed("Enter code QWERTY12") == (pp.DEFAULT_LINK, "QWERTY12")


@pytest.mark.parametrize("line", ["Enter code to continue", "Enter code abc", "Go to https://www.microsoft.com/link",
                                  "Copied code to clipboard", "Enter the code"])
def test_lines_that_are_not_a_code_never_produce_one(line):
    assert pp.DeviceCodeParser().feed(line) is None


def test_login_shows_a_code_that_arrives_on_its_own_line(proxy_dir, monkeypatch):
    import threading

    class TwoLineSession:
        def __init__(self, on_line=None):
            self.on_line = on_line

        def start(self):
            self.on_line("[INFO ]: Go to https://www.microsoft.com/link")
            self.on_line("[INFO ]: Enter code 59EW7MQL")
            proxy_dir.mkdir(parents=True, exist_ok=True)
            (proxy_dir / "auth.json").write_text("{}")

        def alive(self):
            return True

        def stop(self):
            pass

    monkeypatch.setattr(pp, "ProxySession", TwoLineSession)
    got, done = [], threading.Event()
    pp.ProxyLogin().start(lambda url, code: got.append((url, code)), done.set)
    assert done.wait(5) and got == [("https://www.microsoft.com/link", "59EW7MQL")]


# ---- the default server (Hive) and the proxy that pointed at itself
def test_the_hive_is_a_ready_made_server_and_is_recognised_by_its_address():
    assert ("hive", "Hive", "geo.hivebedrock.network", "19132") in pp.SERVER_PRESETS
    assert pp.preset_for("GEO.HiveBedrock.network", 19132) == "hive"
    assert pp.preset_for("example.net", "19132") is None


def test_a_new_config_forwards_to_the_hive_and_listens_on_this_computer_only(proxy_dir):
    pp.ensure_local_listen()
    text = (proxy_dir / "config.yml").read_text()
    assert "destination:\n  host: geo.hivebedrock.network\n  port: 19132" in text
    assert "proxy:\n  host: 127.0.0.1" in text


def test_a_destination_that_is_the_proxys_own_address_is_replaced_not_kept(proxy_dir):
    """Older configs forwarded 127.0.0.1:19132 to 127.0.0.1:19132: nothing could ever be reached."""
    proxy_dir.mkdir()
    (proxy_dir / "config.yml").write_text(
        "proxy:\n  host: 127.0.0.1\n  port: 19132\ndestination:\n  host: 127.0.0.1\n  port: 19132\nonline-mode: true\n")
    assert pp.read_destination() == ("geo.hivebedrock.network", "19132")      # what the page shows
    pp.ensure_destination()
    text = (proxy_dir / "config.yml").read_text()
    assert "host: geo.hivebedrock.network" in text and "online-mode: true" in text
    assert text.count("127.0.0.1") == 1                                         # only the listen side is left


def test_a_server_the_player_chose_is_never_overwritten(proxy_dir):
    pp.write_destination("play.example.net", 25565)
    pp.ensure_destination()
    assert pp.read_destination() == ("play.example.net", "25565")
    pp.write_destination("127.0.0.1", 25565)                  # loopback on another port is a real local server
    pp.ensure_destination()
    assert pp.read_destination() == ("127.0.0.1", "25565")


def test_the_proxy_is_never_written_into_the_games_server_list():
    """A saved 127.0.0.1:19132 entry made the game stop listing the ProxyPass world, and
    the Play button of a saved server is disabled while the game is signed out."""
    import ast
    from pathlib import Path
    from gomceix.core import launch
    tree = ast.parse(Path(launch.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "seed_default_servers"]
    assert calls and all(not any(k.arg == "servers" for k in c.keywords) for c in calls)
    from gomceix.core.prefix import DEFAULT_SERVERS
    assert not any(host.startswith("127.") for _n, host, _p in DEFAULT_SERVERS)
    # ...and one that is already there (older build, or added by hand) goes, in ProxyPass mode only.
    guarded = [n for n in ast.walk(tree) if isinstance(n, ast.If) and getattr(n.test, "id", "") == "proxy_mode"
               and any(getattr(c.func, "id", "") == "forget_servers_at_this_computer"
                       for c in ast.walk(n) if isinstance(c, ast.Call))]
    assert guarded
