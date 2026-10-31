"""Audit regressions for component removal: links, settings, running proxy, failures."""
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
    null = lambda *a, **k: contextlib.nullcontext()
    from gomceix.core import engine_lock, prefix
    monkeypatch.setattr(prefix, "shared_assets_lock", null)
    monkeypatch.setattr(prefix, "prefix_operation_lock", null)
    monkeypatch.setattr(engine_lock, "managed_engine_lock", null)
    saved = {}
    monkeypatch.setattr(comps, "load_settings", lambda: dict(saved))
    monkeypatch.setattr(comps, "save_settings", lambda s: (saved.clear(), saved.update(s)))
    monkeypatch.setattr(config, "_test_saved", saved, raising=False)
    return root


@pytest.fixture
def saved():
    return config._test_saved


def _engine(data):
    engine = config.WINEGDK_OUT
    engine.mkdir(parents=True)
    (engine / "proton").write_text("x")
    return engine


def test_removing_the_engine_forgets_it_in_the_settings(data, saved):
    engine = _engine(data)
    saved.update(proton=str(engine), proton_tag="winegdk", proton_source="winegdk", other=1)
    comps.remove("engine")
    assert not engine.exists()
    assert "proton" not in saved and "proton_tag" not in saved
    assert saved["other"] == 1 and saved["proton_source"] == "winegdk"


def test_a_custom_engine_in_the_settings_is_not_forgotten(data, saved, tmp_path):
    _engine(data)
    custom = tmp_path / "my-proton"
    custom.mkdir()
    saved.update(proton=str(custom), proton_tag="custom-dir")
    comps.remove("engine")
    assert saved["proton"] == str(custom) and custom.exists()


def test_a_component_folder_that_is_a_link_out_of_data_only_loses_the_link(data, tmp_path):
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "f").write_text("keep")
    (data / "umu").symlink_to(outside)
    comps.remove("umu")
    assert not (data / "umu").exists() and not (data / "umu").is_symlink()
    assert (outside / "f").read_text() == "keep"


def test_a_parent_folder_that_is_a_link_out_of_data_is_refused(data, tmp_path):
    outside = tmp_path / "elsewhere"
    (outside / "java-25").mkdir(parents=True)
    (outside / "java-25" / "f").write_text("keep")
    (data / "runtime").symlink_to(outside)
    with pytest.raises(BolError):
        comps.remove("java")
    assert (outside / "java-25" / "f").exists()


def test_a_data_folder_that_is_itself_a_link_still_works(tmp_path, monkeypatch, data):
    real = tmp_path / "real-data"
    real.mkdir()
    link = tmp_path / "linked-data"
    link.symlink_to(real)
    monkeypatch.setattr(config, "DATA", link)
    monkeypatch.setattr(config, "UMU_DIR", link / "umu")
    (real / "umu").mkdir()
    (real / "umu" / "umu-run").write_text("x")
    comps.remove("umu")
    assert not (real / "umu").exists() and real.exists()
    monkeypatch.setattr(config, "UMU_DIR", link)            # DATA itself, by its link name
    with pytest.raises(BolError):
        comps.remove("umu")
    assert real.exists()


def test_dotdot_in_a_target_cannot_climb_out(data, tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    victim.mkdir()
    monkeypatch.setattr(config, "UMU_DIR", data / "sub" / ".." / ".." / "victim")
    with pytest.raises(BolError):
        comps.remove("umu")
    assert victim.exists()


def test_java_and_proxypass_are_not_removed_while_a_proxy_runs(data, monkeypatch):
    (data / "proxypass").mkdir()
    (data / "proxypass" / "ProxyPass.jar").write_text("x")
    monkeypatch.setattr(proxypass, "session_running", lambda: True)
    for cid in ("java", "proxypass"):
        with pytest.raises(BolError, match="running"):
            comps.remove(cid)
    assert (data / "proxypass" / "ProxyPass.jar").exists()
    comps.remove("umu")                                   # unrelated components are unaffected


def test_a_failed_deletion_is_a_bolerror_the_ui_can_show(data, monkeypatch):
    (data / "umu").mkdir()

    def boom(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(comps, "remove_path", boom)
    with pytest.raises(BolError, match="Could not remove"):
        comps.remove("umu")


def test_a_deletion_that_only_fails_once_is_retried(data, monkeypatch):
    (data / "umu").mkdir()
    real, calls = comps.remove_path, []

    def flaky(path):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(39, "Directory not empty")
        real(path)

    monkeypatch.setattr(comps, "remove_path", flaky)
    comps.remove("umu")
    assert len(calls) == 2 and not (data / "umu").exists()
