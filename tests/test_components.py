"""Components are removed only from inside Gomceix's own data folder."""
import contextlib

import pytest

from gomceix.core import components as comps
from gomceix.core import config, proxypass
from gomceix.core.log import BolError


@pytest.fixture
def data(tmp_path, monkeypatch):
    root = tmp_path / "gomceix"
    root.mkdir()
    for name, value in {"DATA": root, "CACHE": root / "cache", "UMU_DIR": root / "umu",
                        "XODUS_DIR": root / "xodus", "PROTON_DIR": root / "proton",
                        "WINEGDK_OUT": root / "proton" / "GDK-Proton-xuser",
                        "XODUS_WEBVIEW_DIR": root / "xodus-webview",
                        "OPENSSL_XCURL_SET": root / "xodus-xcurl" / "openssl-set"}.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(proxypass, "PROXY_DIR", root / "proxypass")
    monkeypatch.setattr(proxypass, "JAR", root / "proxypass" / "ProxyPass.jar")
    monkeypatch.setattr(proxypass, "RUNTIME_DIR", root / "runtime")
    null = lambda *a, **k: contextlib.nullcontext()          # no lock files outside tmp_path
    from gomceix.core import engine_lock, prefix
    monkeypatch.setattr(prefix, "shared_assets_lock", null)
    monkeypatch.setattr(prefix, "prefix_operation_lock", null)
    monkeypatch.setattr(engine_lock, "managed_engine_lock", null)
    return root


def test_size_counts_files_without_following_links(data, tmp_path):
    (data / "umu").mkdir()
    (data / "umu" / "umu-run").write_bytes(b"x" * 100)
    (data / "umu" / "link").symlink_to(tmp_path)           # must not be walked
    assert comps.size_bytes("umu") == 100
    assert comps.size_bytes("java") == 0


def test_removing_a_component_deletes_only_its_folder(data):
    (data / "umu").mkdir()
    (data / "umu" / "umu-run").write_text("x")
    (data / "settings.json").write_text("{}")
    assert comps.get("umu").installed()
    comps.remove("umu")
    assert not (data / "umu").exists() and (data / "settings.json").exists()
    assert not comps.get("umu").installed()


def test_removing_the_proxypass_jar_keeps_the_account_and_the_config(data):
    pdir = data / "proxypass"
    pdir.mkdir()
    for name in ("ProxyPass.jar", "auth.json", "config.yml"):
        (pdir / name).write_text("x")
    comps.remove("proxypass")
    assert sorted(p.name for p in pdir.iterdir()) == ["auth.json", "config.yml"]


def test_the_cache_is_emptied_but_its_folder_stays(data):
    (data / "cache").mkdir()
    (data / "cache" / "a.tar").write_bytes(b"1234")
    (data / "cache" / "sub").mkdir()
    (data / "cache" / "sub" / "b").write_bytes(b"5")
    assert comps.size_bytes("cache") == 5
    comps.remove("cache")
    assert (data / "cache").is_dir() and list((data / "cache").iterdir()) == []


def test_shared_and_unknown_components_are_refused(data):
    with pytest.raises(BolError):
        comps.remove("login-deps")
    with pytest.raises(BolError):
        comps.remove("nonsense")


def test_nothing_outside_the_data_folder_is_ever_deleted(data, tmp_path, monkeypatch):
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "file").write_text("keep")
    monkeypatch.setattr(config, "UMU_DIR", outside)
    with pytest.raises(BolError):
        comps.remove("umu")
    assert (outside / "file").exists()


def test_the_data_folder_itself_cannot_be_a_target(data, monkeypatch):
    monkeypatch.setattr(config, "UMU_DIR", data)
    with pytest.raises(BolError):
        comps.remove("umu")
    assert data.exists()


def test_install_fails_loudly_when_the_component_is_still_missing(data, monkeypatch):
    fake = comps.Component("umu", lambda: (), lambda: False, lambda progress: None)
    monkeypatch.setattr(comps, "get", lambda cid: fake)
    with pytest.raises(BolError):
        comps.install("umu")


def test_a_working_system_webkitgtk_is_not_a_missing_download(data, monkeypatch):
    from gomceix.core import webview
    web = comps.get("webview")
    monkeypatch.setattr(webview, "installed", lambda: False)
    monkeypatch.setattr(webview, "host_works_isolated", lambda: False)
    assert not web.installed() and not web.is_shared()           # no WebKitGTK anywhere: offered as a download
    monkeypatch.setattr(webview, "host_works_isolated", lambda: True)
    assert web.installed() and web.is_shared()                   # the host has it: nothing to fetch or remove
    with pytest.raises(BolError):
        comps.remove("webview")


def test_a_downloaded_webkitgtk_stays_removable_on_a_host_that_has_one(data, monkeypatch):
    from gomceix.core import webview
    web = comps.get("webview")
    monkeypatch.setattr(webview, "installed", lambda: True)
    monkeypatch.setattr(webview, "host_works_isolated", lambda: True)
    assert web.installed() and not web.is_shared()
    (config.XODUS_WEBVIEW_DIR).mkdir()
    comps.remove("webview")
    assert not config.XODUS_WEBVIEW_DIR.exists()
