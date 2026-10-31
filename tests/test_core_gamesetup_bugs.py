"""Setup stage order and the stage callback's failure handling."""
import tempfile
from unittest import mock

import pytest

from gomceix.core import gamesetup
from gomceix.core.log import BolError


def _run(settings, stage, boot=True, ensure_components=None):
    with tempfile.TemporaryDirectory() as td:
        settings = {"game_dir": td, "proton_source": "proton", **settings}
        with mock.patch.object(gamesetup, "mkdirs"), \
                mock.patch.object(gamesetup, "prune_legacy_game_archives"), \
                mock.patch.object(gamesetup, "load_settings", return_value=settings), \
                mock.patch.object(gamesetup, "ensure_login_deps"), \
                mock.patch.object(gamesetup, "_game_root", return_value=True), \
                mock.patch.object(gamesetup, "ensure_proton"), \
                mock.patch.object(gamesetup, "ensure_umu"), \
                mock.patch.object(gamesetup, "fix_curl_ssl"), \
                mock.patch.object(gamesetup, "boot_prefix", return_value=boot), \
                mock.patch.object(gamesetup, "install_gameinput"), \
                mock.patch.object(gamesetup, "hide_signin_button"), \
                mock.patch.object(gamesetup, "active_prefix"), \
                mock.patch.object(gamesetup.hostarch, "problem", return_value=None), \
                mock.patch.object(gamesetup.proxypass, "ensure_components",
                                  side_effect=ensure_components or (lambda p, version=None: ("j", "j"))), \
                mock.patch.object(gamesetup.proxypass, "in_use_game_version", return_value=None), \
                mock.patch.object(gamesetup.proxypass, "support_problem", return_value=None), \
                mock.patch.object(gamesetup, "warn") as warned, \
                mock.patch.object(gamesetup, "ok"):
            gamesetup._do_setup(stage=stage)
    return warned


def test_stage_order_with_and_without_proxypass():
    seen = []
    _run({}, seen.append)
    assert seen == ["deps", "game", "engine", "prefix", "finish"]
    seen.clear()
    _run({"login_mode": "proxypass"}, seen.append)
    assert seen == ["deps", "game", "engine", "proxy", "prefix", "finish"]


def test_a_stage_callback_that_raises_never_breaks_the_install_and_is_reported_once():
    def bad(_name):
        raise RuntimeError("widget gone")

    warned = _run({}, bad)
    assert warned.call_count == 1
    assert "RuntimeError" in warned.call_args.args[0]


def test_a_proxypass_download_failure_stops_setup_before_the_prefix():
    seen = []

    def fail(_progress, _version=None):
        raise BolError("no network")

    with pytest.raises(BolError, match="no network"):
        _run({"login_mode": "proxypass"}, seen.append, ensure_components=fail)
    assert seen[-1] == "proxy"
