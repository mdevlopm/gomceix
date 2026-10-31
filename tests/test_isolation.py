"""The suite runs against a throw-away home, never the real data folder (see conftest.py)."""
import os
import tempfile
from pathlib import Path

from gomceix.core import config


def test_the_suite_never_points_at_the_real_data_folder():
    tmp = Path(tempfile.gettempdir()).resolve()
    assert Path(os.environ["HOME"]).resolve().is_relative_to(tmp)
    for path in (config.DATA, config.PFX, config.XDG_CONFIG_HOME):
        assert Path(path).resolve().is_relative_to(Path(os.environ["HOME"]).resolve())
