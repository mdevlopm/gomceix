"""ProxyPass speaks one Bedrock protocol: each build only works with the game version it was made for."""
import hashlib

import pytest

from gomceix.core import gamesetup, proxypass as pp
from gomceix.core.log import BolError


def release(tag, change, prerelease=False, digest="0" * 64, name="ProxyPass.jar"):
    return {"tag_name": tag, "prerelease": prerelease, "draft": False,
            "body": f"## Changes: [`abc...abc`](https://example.invalid)\n- {change} \\(\\#1\\)",
            "assets": [{"name": name, "browser_download_url": f"https://example.invalid/{tag}/{name}",
                        "digest": f"sha256:{digest}", "size": 10}]}


RELEASES = [  # newest first, as GitHub returns them (taken from the real release list)
    release("master-67", "1.26.30"),
    release("pre/1.26.30-2", "Add block packets", prerelease=True),
    release("master-66", "1.26.20"),
    release("master-65", "Pre-inserts OTC"),
    release("master-64", "1.26.10"),
    release("master-63", "Fix NPE for old Nethernet signaling"),
]


@pytest.fixture(autouse=True)
def proxy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PROXY_DIR", tmp_path / "proxypass")
    monkeypatch.setattr(pp, "JAR", tmp_path / "proxypass" / "ProxyPass.jar")
    monkeypatch.setattr(pp.util, "gh_releases", lambda *a, **k: RELEASES)
    return tmp_path / "proxypass"


def test_each_game_version_maps_to_the_build_made_for_it():
    found = pp.builds()
    assert set(found) == {"1.26.30", "1.26.20", "1.26.10"}       # fixes without a version line, and pre-releases, are not offered
    assert found["1.26.30"]["tag_name"] == "master-67"
    assert pp.supported_versions() == ["1.26.30", "1.26.20", "1.26.10"]


@pytest.mark.parametrize("tag,key", [("1.26.30.2", "1.26.30"), ("v1.21.50", "1.21.50"), ("26.30", None), ("", None), (None, None)])
def test_game_key(tag, key):
    assert pp.game_key(tag) == key


def test_a_version_without_a_build_is_refused_with_the_ones_that_work():
    problem = pp.support_problem("1.26.60.1")
    assert "26.60" in problem and "26.30, 26.20, 26.10" in problem and "Normal mode" in problem
    assert pp.support_problem("1.26.30.5") is None


def test_nothing_is_blocked_when_the_build_list_is_unknown(monkeypatch):
    monkeypatch.setattr(pp.util, "gh_releases", lambda *a, **k: [])
    assert pp.support_problem("1.26.60.1") is None            # offline: do not guess


def test_an_already_downloaded_jar_makes_its_version_playable_offline(proxy_dir, monkeypatch):
    import zipfile
    proxy_dir.mkdir()
    with zipfile.ZipFile(proxy_dir / "ProxyPass-1.26.60.jar", "w") as z:
        z.writestr("a", "b")
    assert pp.support_problem("1.26.60.1") is None
    assert pp.ensure_jar(version="1.26.60.1").endswith("ProxyPass-1.26.60.jar")


def _fake_download(content):
    def download(url, dest, label=None, progress=None, attempts=5):
        dest.write_bytes(content)
    return download


def jar_bytes():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Main.class", "x")
    return buf.getvalue()


def test_the_jar_for_the_game_version_is_downloaded_verified_and_cached(proxy_dir, monkeypatch):
    content = jar_bytes()
    digest = hashlib.sha256(content).hexdigest()
    releases = [release("master-66", "1.26.20", digest=digest)]
    monkeypatch.setattr(pp.util, "gh_releases", lambda *a, **k: releases)
    monkeypatch.setattr(pp.util, "download", _fake_download(content))
    path = pp.ensure_jar(version="1.26.20.3")
    assert path.endswith("ProxyPass-1.26.20.jar") and pp.jar_ok(path)
    monkeypatch.setattr(pp.util, "download", lambda *a, **k: pytest.fail("a cached jar was downloaded again"))
    assert pp.ensure_jar(version="1.26.20.9") == path


def test_a_jar_that_does_not_match_the_published_checksum_is_not_installed(proxy_dir, monkeypatch):
    releases = [release("master-66", "1.26.20", digest="f" * 64)]
    monkeypatch.setattr(pp.util, "gh_releases", lambda *a, **k: releases)
    monkeypatch.setattr(pp.util, "download", _fake_download(jar_bytes()))
    with pytest.raises(BolError, match="checksum"):
        pp.ensure_jar(version="1.26.20.3")
    assert not (proxy_dir / "ProxyPass-1.26.20.jar").exists()


def test_asking_for_an_unsupported_version_never_downloads_anything(monkeypatch):
    monkeypatch.setattr(pp.util, "download", lambda *a, **k: pytest.fail("downloaded"))
    with pytest.raises(BolError, match="no build for Minecraft 26.60"):
        pp.ensure_jar(version="1.26.60.1")


def test_setup_refuses_an_unsupported_version_before_downloading_the_game(monkeypatch):
    from unittest import mock
    calls = []
    with mock.patch.object(gamesetup, "mkdirs"), mock.patch.object(gamesetup, "prune_legacy_game_archives"), \
            mock.patch.object(gamesetup, "load_settings", return_value={"login_mode": "proxypass"}), \
            mock.patch.object(gamesetup.hostarch, "problem", return_value=None), \
            mock.patch.object(gamesetup, "ensure_login_deps", side_effect=lambda: calls.append("deps")), \
            mock.patch.object(gamesetup, "install_game", side_effect=lambda *a, **k: calls.append("game")):
        with pytest.raises(BolError, match="no build for Minecraft 26.60"):
            gamesetup._do_setup(mc_edition="release", mc_version="1.26.60.1")
    assert calls == []


def test_setup_with_online_mode_off_downloads_a_version_without_a_build(monkeypatch):
    from unittest import mock
    pp.write_online_mode(False)
    with mock.patch.object(gamesetup, "mkdirs"), mock.patch.object(gamesetup, "prune_legacy_game_archives"), \
            mock.patch.object(gamesetup, "load_settings", return_value={"login_mode": "proxypass"}), \
            mock.patch.object(gamesetup.hostarch, "problem", return_value=None), \
            mock.patch.object(gamesetup, "ensure_login_deps"), \
            mock.patch.object(gamesetup, "install_game", side_effect=KeyError("reached the download")):
        with pytest.raises(KeyError, match="reached the download"):
            gamesetup._do_setup(mc_edition="release", mc_version="1.26.60.1")


# ---- finding the Java runtime download (Adoptium sometimes answers 406/5xx to a good request)
import urllib.error  # noqa: E402

JAVA_PACKAGE = {"binary": {"package": {"link": "https://example.invalid/OpenJDK25U-jre.tar.gz",
                                       "name": "OpenJDK25U-jre.tar.gz", "checksum": "a" * 64}}}


def _http_error(code):
    return urllib.error.HTTPError("https://api.adoptium.net/x", code, "Not Acceptable", {}, None)


def test_a_one_off_406_from_adoptium_is_retried_and_succeeds(monkeypatch):
    seen = []

    def http_json(url, timeout=10, accept="x"):
        seen.append(accept)
        if len(seen) == 1:
            raise _http_error(406)
        return [JAVA_PACKAGE]

    monkeypatch.setattr(pp.util, "http_json", http_json)
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    assert pp._java_package() == ("https://example.invalid/OpenJDK25U-jre.tar.gz", "OpenJDK25U-jre.tar.gz", "a" * 64)
    assert len(seen) == 2 and seen[0] == "application/json"       # never GitHub's media type for Adoptium


def test_when_adoptium_stays_down_temurins_github_release_is_used(monkeypatch):
    monkeypatch.setattr(pp.util, "http_json", lambda *a, **k: (_ for _ in ()).throw(_http_error(406)))
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    name = "OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz"
    release = {"assets": [
        {"name": name + ".sha256.txt", "browser_download_url": "https://example.invalid/x.txt", "digest": "sha256:" + "c" * 64},
        {"name": name, "browser_download_url": "https://example.invalid/" + name, "digest": "sha256:" + "b" * 64, "size": 1}]}
    monkeypatch.setattr(pp.util, "gh_latest", lambda repo: release)
    assert pp._java_package() == ("https://example.invalid/" + name, name, "b" * 64)


def test_a_java_lookup_that_fails_everywhere_says_so_plainly(monkeypatch):
    monkeypatch.setattr(pp.util, "http_json", lambda *a, **k: (_ for _ in ()).throw(_http_error(406)))
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    monkeypatch.setattr(pp.util, "gh_latest", lambda repo: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(BolError, match="Could not look up the Java runtime download"):
        pp._java_package()


def test_a_download_without_a_published_checksum_is_never_accepted(monkeypatch):
    bad = {"binary": {"package": {"link": "https://example.invalid/j.tar.gz", "name": "j.tar.gz", "checksum": ""}}}
    monkeypatch.setattr(pp.util, "http_json", lambda *a, **k: [bad])
    monkeypatch.setattr(pp.util, "gh_latest", lambda repo: {"assets": []})
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    with pytest.raises(BolError):
        pp._java_package()


def test_the_refusal_is_shown_in_the_chosen_language(monkeypatch):
    from gomceix import i18n
    monkeypatch.setattr(i18n, "_catalog", {
        "ProxyPass has no build for Minecraft {version}. It works with: {listed}. Pick one of those versions, or use Normal mode.":
            "{version} yok; olanlar: {listed}"})
    assert pp.support_problem("1.26.60.1").startswith("26.60 yok; olanlar: 26.30, 26.20, 26.10")
