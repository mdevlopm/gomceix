"""Regression tests for the Store sign-in cancel race (B11) and the download stall watchdog (B12)."""
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from gomceix.core import xodus
from tests.test_xodus import SH, _own_home


def _binary(tmp, script):
    binary = Path(tmp) / "xodus-cli"
    binary.write_text(f"#!{SH}\n" + script, encoding="utf-8")
    binary.chmod(0o755)
    return binary


class CancelRaceTests(unittest.TestCase):
    def setUp(self):
        xodus._LOGIN.update(proc=None, cancelled=False, starting=False)
        self.addCleanup(xodus._LOGIN.update, proc=None, cancelled=False, starting=False)

    def test_cancel_between_popen_and_the_stored_process_still_closes_the_window(self):
        real_popen = subprocess.Popen
        spawned = []

        def popen_then_cancel(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            spawned.append(proc)
            # The user pressed Cancel right now: the process exists, but login()
            # has not stored it yet.
            self.assertTrue(xodus.cancel_login())
            return proc

        with tempfile.TemporaryDirectory() as tmp, _own_home(tmp), \
                mock.patch.object(xodus, "ensure_cli", return_value=_binary(tmp, "sleep 30\n")), \
                mock.patch.object(xodus, "LOGIN_LOG", Path(tmp) / "login.log"), \
                mock.patch.object(xodus.webview, "apply", return_value={}), \
                mock.patch.object(xodus.subprocess, "Popen", popen_then_cancel):
            started = time.monotonic()
            with self.assertRaises(xodus.LoginCancelled):
                xodus.login()
            self.assertLess(time.monotonic() - started, 20)
        self.assertIsNotNone(spawned[0].poll(), "the sign-in process was left running")
        self.assertFalse(xodus.login_running())

    def test_cancel_while_the_cli_is_being_prepared_never_opens_a_window(self):
        def cancel_during_download():
            self.assertTrue(xodus.cancel_login())
            return Path("/nonexistent/xodus-cli")

        with tempfile.TemporaryDirectory() as tmp, _own_home(tmp), \
                mock.patch.object(xodus, "ensure_cli", side_effect=cancel_during_download), \
                mock.patch.object(xodus, "LOGIN_LOG", Path(tmp) / "login.log"), \
                mock.patch.object(xodus.webview, "apply", return_value={}), \
                mock.patch.object(xodus.subprocess, "Popen") as popen:
            with self.assertRaises(xodus.LoginCancelled):
                xodus.login()
        popen.assert_not_called()

    def test_cancel_with_nothing_running_still_reports_false(self):
        self.assertFalse(xodus.cancel_login())

    def test_a_second_login_is_refused_while_the_first_is_still_starting(self):
        xodus._LOGIN["starting"] = True
        with self.assertRaises(xodus.XodusError):
            xodus.login()


class StallWatchdogTests(unittest.TestCase):
    def test_the_full_disk_retry_line_does_not_count_as_progress(self):
        error = "No space left on device (os error 28)"
        with tempfile.TemporaryDirectory() as tmp, _own_home(tmp), \
                mock.patch.object(xodus, "DOWNLOAD_LOG", Path(tmp) / "dl.log"), \
                mock.patch.object(xodus.webview, "apply", return_value={}), \
                mock.patch.object(xodus, "_STALL_NOTICE", 1), \
                mock.patch.object(xodus, "_STALL_LIMIT", 2), \
                mock.patch.object(xodus, "warn"):
            # The real tool repeats this line; here every 0.2 s for a minute.
            binary = _binary(tmp, "i=0\nwhile [ $i -lt 300 ]; do\n"
                             f"  echo 'Error write file {error} waiting 30s'\n"
                             "  sleep 0.2\n  i=$((i + 1))\ndone\n")
            started = time.monotonic()
            code, tail = xodus._run_streaming(
                [str(binary), "streaming", "http://assets1.example/p", str(Path(tmp) / "dest")])
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 20, "the watchdog never fired")
        self.assertNotEqual(code, 0)
        self.assertIn("Nothing reached the download", tail[-1])
        self.assertIn("could not write to the disk", tail[-1])

    def test_real_output_still_keeps_a_download_alive(self):
        frame = ("printf 'Downloading                       1.00 MiB/    "
                 "2.00 GiB  1.00 MiB/s [#>---] 0%%\\r'\n")
        with tempfile.TemporaryDirectory() as tmp, _own_home(tmp), \
                mock.patch.object(xodus, "DOWNLOAD_LOG", Path(tmp) / "dl.log"), \
                mock.patch.object(xodus.webview, "apply", return_value={}), \
                mock.patch.object(xodus, "_STALL_NOTICE", 1), \
                mock.patch.object(xodus, "_STALL_LIMIT", 2), \
                mock.patch.object(xodus, "warn") as warned:
            binary = _binary(tmp, "i=0\nwhile [ $i -lt 8 ]; do\n  " + frame
                             + "  sleep 0.4\n  i=$((i + 1))\ndone\nexit 0\n")
            code, _tail = xodus._run_streaming(
                [str(binary), "streaming", "http://assets1.example/p", str(Path(tmp) / "dest")])
        self.assertEqual(code, 0)
        warned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
