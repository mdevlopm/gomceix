"""Only stop signals nobody else took are deferred: `nohup` must keep working."""
import subprocess
import sys


def test_an_ignored_signal_is_left_alone():
    code = ("import signal; from gomceix.core import supervision;"
            "signal.signal(signal.SIGHUP, signal.SIG_IGN);"
            "print(signal.SIGHUP in supervision.default_signals(), signal.SIGTERM in supervision.default_signals())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["False", "True"]

