"""The CA bundle the game trusts is refreshed, not kept forever."""
# SPDX-License-Identifier: MIT

import os
import time

import pytest

from gomceix.core import fixups
from gomceix.core.log import BolError


def _bundle(cache, age_days, text="old bundle"):
    cacert = cache / "cacert.pem"
    cacert.write_text(text)
    stamp = time.time() - age_days * 86400
    os.utime(cacert, (stamp, stamp))
    return cacert


def _fetcher(calls, text="new bundle"):
    def fetch(_url, dest, _label=None, *_args, **_kwargs):
        calls.append(dest)
        dest.write_text(text)
    return fetch


def test_a_missing_bundle_is_downloaded(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", _fetcher(calls))
    assert fixups._cacert().read_text() == "new bundle"
    assert len(calls) == 1


def test_a_recent_bundle_is_reused(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", _fetcher(calls))
    _bundle(tmp_path, age_days=3)
    assert fixups._cacert().read_text() == "old bundle"
    assert calls == []


def test_an_old_bundle_is_fetched_again(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", _fetcher(calls))
    _bundle(tmp_path, age_days=45)
    assert fixups._cacert().read_text() == "new bundle"


def test_an_old_bundle_is_kept_when_the_refresh_fails(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise BolError("offline")

    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", offline)
    monkeypatch.setattr(fixups, "warn", lambda _message: None)
    _bundle(tmp_path, age_days=45)
    assert fixups._cacert().read_text() == "old bundle"


def test_with_no_bundle_a_failed_download_is_an_error(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise BolError("offline")

    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", offline)
    with pytest.raises(BolError):
        fixups._cacert()


def test_a_failed_refresh_tries_once_and_not_again_on_the_next_play(tmp_path, monkeypatch):
    attempts = []

    def offline(*_args, **kwargs):
        attempts.append(kwargs.get("attempts"))
        raise BolError("offline")

    monkeypatch.setattr(fixups, "CACHE", tmp_path)
    monkeypatch.setattr(fixups, "download", offline)
    monkeypatch.setattr(fixups, "warn", lambda _message: None)
    _bundle(tmp_path, age_days=45)
    fixups._cacert()
    fixups._cacert()
    assert attempts == [1]
    age = time.time() - (tmp_path / "cacert.pem").stat().st_mtime
    assert age > fixups.CACERT_MAX_AGE - fixups.CACERT_RETRY_AFTER - 60     # tried again in a day
