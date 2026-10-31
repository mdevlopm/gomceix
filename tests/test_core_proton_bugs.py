"""Stock GDK-Proton is installed only against a published digest (B6); patching is atomic (B13)."""
import hashlib
import io
import os
import tarfile

import pytest

from gomceix.core import pe, proton
from gomceix.core.log import BolError


def _tar(path):
    with tarfile.open(path, "w:gz") as tf:
        data = b"#!/bin/sh\n"
        member = tarfile.TarInfo("GDK-Proton-x/proton")
        member.size, member.mode = len(data), 0o755
        tf.addfile(member, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def stock(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(proton, "CACHE", cache)
    monkeypatch.setattr(proton, "PROTON_DIR", tmp_path / "proton")
    monkeypatch.setattr(proton, "load_settings", lambda: {})
    monkeypatch.setattr(proton, "save_settings", lambda s: None)
    monkeypatch.delenv("GOMCEIX_ALLOW_UNPINNED_PROTON", raising=False)
    calls = []
    source = tmp_path / "served.tar.gz"
    digest = _tar(source)

    def fake_download(url, dest, label=None, progress=None, attempts=5):
        calls.append(url)
        dest.write_bytes(source.read_bytes())
        return dest

    monkeypatch.setattr(proton, "download", fake_download)
    return cache, calls, digest


def _release(digest=None, name="GDK-Proton-x.tar.gz"):
    asset = {"name": name, "browser_download_url": "https://example.invalid/" + name}
    if digest:
        asset["digest"] = "sha256:" + digest
    return {"tag_name": "t1", "assets": [asset]}


def test_a_release_without_a_digest_is_refused_before_downloading(stock, monkeypatch):
    _cache, calls, _digest = stock
    monkeypatch.setattr(proton, "gh_latest", lambda repo: _release())
    with pytest.raises(BolError, match="SHA-256"):
        proton.ensure_proton(force=True)
    assert calls == []


def test_the_unpinned_download_can_be_allowed_explicitly(stock, monkeypatch):
    _cache, calls, _digest = stock
    monkeypatch.setattr(proton, "gh_latest", lambda repo: _release())
    monkeypatch.setenv("GOMCEIX_ALLOW_UNPINNED_PROTON", "1")
    tar = proton._fetch_stock_archive(_release(), "t1", "u", "GDK-Proton-x.tar.gz", {}, None)
    assert tar.is_file() and calls == ["u"]


def test_a_matching_digest_installs(stock):
    cache, calls, digest = stock
    tar = proton._fetch_stock_archive(_release(digest), "t1", "u", "GDK-Proton-x.tar.gz", {}, None)
    assert tar == cache / "GDK-Proton-x.tar.gz" and calls == ["u"]


def test_a_wrong_digest_deletes_the_download_and_refuses(stock):
    cache, _calls, _digest = stock
    with pytest.raises(BolError, match="does not match"):
        proton._fetch_stock_archive(_release("0" * 64), "t1", "u", "GDK-Proton-x.tar.gz", {}, None)
    assert not (cache / "GDK-Proton-x.tar.gz").exists()


def test_a_stale_cached_archive_is_not_trusted(stock):
    cache, calls, digest = stock
    (cache / "GDK-Proton-x.tar.gz").write_bytes(b"from some other release")
    proton._fetch_stock_archive(_release(digest), "t1", "u", "GDK-Proton-x.tar.gz", {}, None)
    assert calls == ["u"]            # re-downloaded rather than reused


def test_a_good_cached_archive_is_reused(stock):
    cache, calls, _digest = stock
    digest = _tar(cache / "GDK-Proton-x.tar.gz")
    proton._fetch_stock_archive(_release(digest), "t1", "u", "GDK-Proton-x.tar.gz", {}, None)
    assert calls == []


def test_atomic_write_replaces_whole_file_keeps_mode_and_leaves_no_temp(tmp_path):
    target = tmp_path / "ntdll.dll"
    target.write_bytes(b"old")
    target.chmod(0o755)
    pe.atomic_write_bytes(target, b"new!")
    assert target.read_bytes() == b"new!"
    assert target.stat().st_mode & 0o777 == 0o755
    assert [p.name for p in tmp_path.iterdir()] == ["ntdll.dll"]


def test_a_failed_atomic_write_leaves_the_original_untouched(tmp_path, monkeypatch):
    target = tmp_path / "combase.dll"
    target.write_bytes(b"original")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        pe.atomic_write_bytes(target, b"patched")
    monkeypatch.undo()
    assert target.read_bytes() == b"original"
    assert [p.name for p in tmp_path.iterdir()] == ["combase.dll"]
