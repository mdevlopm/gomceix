"""Launch clean-up must be exception-safe (B19); ProxyPass is started before and stopped after the game."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gomceix.core import launch
from tests.test_launch import ReadyLaunchHarness


def _popen(*_a, **_kw):
    proc = mock.Mock()
    proc.wait.return_value = 0
    return proc


class TeardownTests(ReadyLaunchHarness, unittest.TestCase):
    def _play(self, **kw):
        with tempfile.TemporaryDirectory() as td:
            return self._exercise_ready_launch(
                Path(td), _popen, arm=lambda: "tok", disarm=lambda _t: True, **kw)

    def test_a_failing_cleanup_step_does_not_fail_the_session(self):
        with mock.patch.object(launch, "_keep_latest_proton_log",
                               side_effect=OSError("disk error")):
            rc = self._play()
        self.assertEqual(rc, 0)
        self.assertTrue(any("Proton log" in w and "OSError" in w for w in self._warnings()))
        # the options clean-up ran before the failing step and the game exit was still reported
        self.assertIn("restore_frame_limits", self.options_calls)

    def test_teardown_step_swallows_only_into_a_warning(self):
        with mock.patch.object(launch, "warn") as warned:
            self.assertEqual(launch._teardown_step("x", lambda: 1 / 0, default="d"), "d")
            self.assertEqual(launch._teardown_step("y", lambda a: a + 1, 1), 2)
        self.assertEqual(warned.call_count, 1)
        self.assertIn("ZeroDivisionError", warned.call_args.args[0])

    def test_a_proton_log_that_vanishes_between_glob_and_stat_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            logs = Path(td)
            (logs / "steam-1.log").write_text("old")
            (logs / "steam-2.log").write_text("new")
            real_stat = Path.stat

            def flaky(self, *a, **k):
                if self.name == "steam-1.log":
                    raise FileNotFoundError(self)
                return real_stat(self, *a, **k)

            with mock.patch.object(launch, "LOGS", logs), mock.patch.object(Path, "stat", flaky):
                launch._keep_latest_proton_log()
            assert (logs / "proton.log").read_text() == "new"


class ProxyModeLaunchTests(ReadyLaunchHarness, unittest.TestCase):
    def setUp(self):
        # Not whatever this computer's own ProxyPass config says about online mode.
        patcher = mock.patch.object(launch.proxypass, "starts_without_proxy", return_value=False)
        self.without_proxy = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(launch.proxypass, "in_use_game_version", return_value="1.26.30.2")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _play(self, session_cls, popen=_popen, **kw):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(launch.proxypass, "ProxySession", session_cls):
            return self._exercise_ready_launch(
                Path(td), popen, arm=lambda: "tok", disarm=lambda _t: True,
                extra_settings={"login_mode": "proxypass"}, **kw)

    def test_the_proxy_runs_for_exactly_the_length_of_the_game(self):
        order = []

        class Session:
            def __init__(self, *a, **k): pass
            def start(self): order.append("proxy-start")
            def stop(self): order.append("proxy-stop")

        def popen(*a, **k):
            order.append("game-start")
            return _popen()

        self._play(Session, popen)
        assert order == ["proxy-start", "game-start", "proxy-stop"]

    def test_online_mode_off_starts_a_version_without_a_build_with_no_proxy(self):
        order = []

        class Session:
            def __init__(self, *a, **k): order.append("proxy")
            def start(self): pass
            def stop(self): pass

        def popen(*a, **k):
            order.append("game-start")
            return _popen()

        self.without_proxy.return_value = True
        self._play(Session, popen)
        assert order == ["game-start"]

    def test_the_log_points_at_the_proxypass_world_only_when_a_proxy_runs(self):
        class Session:
            def __init__(self, *a, **k): pass
            def start(self): pass
            def stop(self): pass

        self._play(Session)
        said = " ".join(self._infos())
        assert "open the ProxyPass world" in said
        assert "already linked" not in said          # the game starts signed out in this mode

        self.without_proxy.return_value = True
        self._play(Session)
        said = " ".join(self._infos())
        assert "ProxyPass world" not in said and "already linked" not in said
        assert any("has no build for 1.26.30.2" in w for w in self._warnings())

    def test_a_proxy_that_cannot_start_stops_the_launch_and_cleans_up(self):
        stopped, disarmed, games = [], [], []

        class Session:
            def __init__(self, *a, **k): pass
            def start(self): raise launch.BolError("Port 19132 is already in use")
            def stop(self): stopped.append(1)

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(launch.proxypass, "ProxySession", Session):
            with self.assertRaises(launch.BolError) as raised:
                self._exercise_ready_launch(
                    Path(td), lambda *a, **k: games.append(1), arm=lambda: "tok",
                    disarm=lambda t: disarmed.append(t) or True,
                    extra_settings={"login_mode": "proxypass"})
        assert "already in use" in str(raised.exception)
        assert games == [] and stopped == [1] and disarmed == ["tok"]

    def test_the_proxy_is_stopped_even_when_the_game_cannot_start(self):
        stopped = []

        class Session:
            def __init__(self, *a, **k): pass
            def start(self): pass
            def stop(self): stopped.append(1)

        def popen(*a, **k):
            raise OSError("no such file")

        with self.assertRaises(OSError):
            self._play(Session, popen)
        assert stopped == [1]
