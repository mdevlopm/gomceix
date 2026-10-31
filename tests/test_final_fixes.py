"""Small defects found in the last review round."""
import threading

import pytest

from gomceix.core import auth, inject, winehelper
from gomceix.core.log import BolError
from tests.test_controller_real import FakeBackend
from gomceix.controller.real import LauncherController


def test_version_flag_prints_the_version(capsys, monkeypatch):
    from gomceix.core import cli
    monkeypatch.setattr("sys.argv", ["gomceix", "--version"])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 0
    assert "Gomceix" in capsys.readouterr().out


def test_a_missing_helper_program_is_a_clear_error_not_a_crash(monkeypatch):
    def gone(*_a):
        raise FileNotFoundError("injector.exe")
    monkeypatch.setattr("pkgutil.get_data", gone)
    assert winehelper.extract("injector.exe") is None
    with pytest.raises(BolError, match="missing"):
        inject._extract_injector()


def test_device_code_failure_reaches_the_window(monkeypatch):
    answers = iter([{"device_code": "d", "user_code": "ABCD1234", "interval": 1, "expires_in": 900},
                    {"error": "expired_token"}])
    monkeypatch.setattr(auth, "http_post_form", lambda *a, **k: next(answers))
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    monkeypatch.setattr(auth, "msa_signed_in", lambda: False)
    monkeypatch.setattr(auth, "_account_cache_epoch", lambda *a: 0)
    errors, done = [], threading.Event()
    flow = auth.NativeAuth()
    flow._flow(lambda *a: None, lambda: None, 0, lambda m: (errors.append(m), done.set()))
    assert done.is_set() and "sign-in failed" in errors[0].lower()


def test_two_builds_never_share_one_label():
    b = FakeBackend()
    b.versions = {"release": [{"version": "1.26.52.1", "installed": False},
                              {"version": "1.26.52.2", "installed": False},
                              {"version": "1.26.40.3", "installed": False}], "preview": []}
    c = LauncherController(b)
    c.refresh_catalog()
    labels = c.versions()
    assert len(labels) == len(set(labels)) == 3
    second = next(l for l in labels if l.endswith("1.26.52.2)"))
    c.set_version(second)
    assert b.settings["mc_version"] == "1.26.52.2"


def test_a_rejected_server_address_tells_the_page_to_restore_the_field():
    b = FakeBackend()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.set_setting("proxypass_host", "bad host")
    assert ("setting-rejected", {"key": "proxypass_host"}) in events


def test_the_advanced_group_offers_the_unverified_download_switches():
    from gomceix.controller.settings import build_groups
    keys = {i.key for g in build_groups() for i in g.items}
    assert {"allow_unpinned_proton", "allow_unpinned_proxypass"} <= keys
