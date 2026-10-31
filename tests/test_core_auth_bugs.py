"""Regression tests for the account-cache lock and the device-code poll (B4, B1 follow-up)."""
import fcntl
import os
import time
import urllib.error

import pytest

from gomceix.core import auth
from gomceix.core.log import BolError


def test_account_cache_lock_gives_up_instead_of_freezing(tmp_path, monkeypatch):
    cache = tmp_path / "winegdk-preauth"
    cache.mkdir()
    holder = os.open(cache / ".account-cache.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)           # a stuck holder
    monkeypatch.setattr(auth, "ACCOUNT_LOCK_TIMEOUT_S", 0.3)
    try:
        started = time.monotonic()
        with pytest.raises(BolError, match="busy"):
            with auth._account_cache_lock(cache):
                pytest.fail("the lock must not be granted while it is held")
        assert time.monotonic() - started < 5
    finally:
        os.close(holder)


def test_account_cache_lock_is_granted_when_the_holder_lets_go(tmp_path, monkeypatch):
    cache = tmp_path / "winegdk-preauth"
    with auth._account_cache_lock(cache):
        pass
    with auth._account_cache_lock(cache):        # released properly: usable again
        pass


def _device_flow(tmp_path, monkeypatch, answers):
    cache = tmp_path / "winegdk-preauth"
    msa = tmp_path / "msa"
    cache.mkdir()
    msa.mkdir()
    epoch = "c" * 32
    (cache / ".account-epoch").write_text(epoch + "\n")
    queue = list(answers)

    def post(url, _data):
        if url == auth.MSA_CONNECT:
            return {"device_code": "dc", "user_code": "CODE", "interval": 1, "expires_in": 900}
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(auth, "DATA", tmp_path)
    monkeypatch.setattr(auth, "MSA_DIR", msa)
    monkeypatch.setattr(auth, "http_post_form", post)
    monkeypatch.setattr(auth.time, "sleep", lambda _s: None)
    monkeypatch.setattr(auth, "info", lambda *_a: None)
    monkeypatch.setattr(auth, "warn", lambda *_a: None)
    monkeypatch.setattr(auth, "err", lambda *_a: None)
    online = []
    auth.NativeAuth()._flow(None, lambda: online.append(1), epoch)
    return msa, online, queue


def test_device_poll_survives_transient_failures(tmp_path, monkeypatch):
    msa, online, left = _device_flow(tmp_path, monkeypatch, [
        urllib.error.URLError("network is down"),
        TimeoutError("slow"),
        ValueError("a 502 page is not JSON"),
        {"error": "temporarily_unavailable"},
        {"error": "authorization_pending"},
        {"refresh_token": "good"},
    ])
    assert online == [1] and not left
    assert (msa / "token.json").is_file()


def test_device_poll_still_stops_on_a_real_refusal(tmp_path, monkeypatch):
    msa, online, left = _device_flow(tmp_path, monkeypatch, [
        {"error": "authorization_declined", "error_description": "no"},
        {"refresh_token": "never-reached"},
    ])
    assert not online and len(left) == 1
    assert not (msa / "token.json").exists()


def test_device_poll_gives_up_when_the_network_stays_down(tmp_path, monkeypatch):
    msa, online, left = _device_flow(
        tmp_path, monkeypatch, [urllib.error.URLError("down")] * 20)
    assert not online and not (msa / "token.json").exists()
    assert len(left) == 20 - (auth._DEVICE_POLL_TRANSIENT_LIMIT + 1)
