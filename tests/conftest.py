"""pytest configuration shared by the whole suite.

Deliberately thin. An earlier version installed a session-wide autouse
fixture that patched gomceix.gui.NativeAuth, which imported gomceix.gui before any
test ran -- so every test in the repository, including the ones about
prefixes, launching and packaging, could only run where PySide6 was
installed. The GUI tests build their own window through tests/guiharness.py
instead, and nothing else has to know the GUI exists.
"""
# SPDX-License-Identifier: MIT

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure gomceix (and tests.*) can be imported however pytest was invoked.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Qt needs a platform plugin at import time and CI has no display. Offscreen
# is set here rather than only in the workflow so a local run behaves the
# same. DISPLAY is deliberately left alone: the display-resolution tests are
# about what the launcher does with the real environment, and a fake value
# planted here would mask that.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The suite never touches the real data folder, settings or Wine prefix. The
# config constants (DATA, PFX, ...) are computed when gomceix.core.config is
# first imported, so the environment has to be redirected here, at conftest
# import, before any test module is collected.
_HOME = tempfile.mkdtemp(prefix="gomceix-tests-")
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)
os.environ.update(HOME=_HOME, XDG_DATA_HOME=_HOME + "/.local/share", XDG_CONFIG_HOME=_HOME + "/.config",
                  XDG_CACHE_HOME=_HOME + "/.cache")
for _name in ("GOMCEIX_HOME", "GOMCEIX_WINEPREFIX"):
    os.environ.pop(_name, None)


def pytest_configure(config):
    config.addinivalue_line("markers", "gui: mark test as a GUI test")
    config.addinivalue_line(
        "markers",
        "requires_display: mark test as requiring an X11/Wayland display")
