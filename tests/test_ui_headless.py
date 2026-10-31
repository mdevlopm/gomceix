"""Runs the headless GTK regression script (tests/ui_regression_check.py).

It needs the system python with PyGObject (the dev venv has none), mutter and a
private D-Bus session; it is skipped where those are missing. Nothing is shown on
the real desktop and no real data folder is touched.
"""
import os
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).with_name("ui_regression_check.py")
SYSTEM_PYTHON = "/usr/bin/python3"


def _can_run():
    if not (shutil.which("mutter") and shutil.which("dbus-run-session") and os.path.exists(SYSTEM_PYTHON)):
        return False
    probe = subprocess.run([SYSTEM_PYTHON, "-c", "import gi; gi.require_version('Adw','1'); gi.require_version('Gtk','4.0')"],
                           capture_output=True)
    return probe.returncode == 0


@pytest.mark.skipif(not _can_run(), reason="needs mutter, dbus-run-session and PyGObject with GTK4/libadwaita")
def test_headless_ui_regressions():
    env = {**os.environ, "PYTHONPATH": str(ROOT), "GTK_A11Y": "none", "GSK_RENDERER": "cairo",
           "LANGUAGE": "en", "LC_ALL": "C", "LANG": "C"}
    # Its own process group, so a timeout can take the compositor down with the script
    # (killing only the first process used to leave a headless mutter running for hours).
    proc = subprocess.Popen(
        ["dbus-run-session", "--", "mutter", "--headless", "--wayland", "--no-x11",
         "--virtual-monitor", "1200x900", "--", SYSTEM_PYTHON, str(SCRIPT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=180)       # about 10 s on an idle machine
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        pytest.fail("the headless UI check took longer than 180 s:\n" + (out or "")[-1500:])
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)       # nothing of it may outlive the test
        except ProcessLookupError:
            pass
    failed = [line for line in out.splitlines() if line.startswith("FAIL")]
    assert not failed, "\n".join(failed)
    assert "RESULT ok" in out, out[-2000:]
