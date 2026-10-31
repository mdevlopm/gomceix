"""A restore that fails part-way leaves the player's data alone and no half copy behind."""
import shutil

import pytest

from gomceix.core import saves
from tests import test_saves

_play = test_saves._play
env = test_saves.env                     # the fixture, shared


def test_a_failed_copy_leaves_no_half_copy_and_keeps_the_data(env, monkeypatch):
    pfx, _settings, _tmp = env
    _play(pfx, worlds=("Mine",))
    source = pfx / "elsewhere" / "Users"
    (source / "x").mkdir(parents=True)
    (source / "x" / "f").write_text("backup")
    real = shutil.copytree

    def dies_midway(src, dst, *args, **kw):
        if str(dst).endswith(saves._INCOMING):
            monkeypatch.setattr(saves.shutil, "copytree", real)   # nested calls are normal
            real(src, dst, *args, **kw)
            raise OSError(28, "No space left on device")
        return real(src, dst, *args, **kw)

    monkeypatch.setattr(saves.shutil, "copytree", dies_midway)
    target = saves.users_dir("release", pfx)
    with pytest.raises(OSError):
        saves._replace_users(source, "release", pfx)
    assert target.is_dir() and any(target.rglob("levelname.txt"))
    assert not target.with_name(saves._INCOMING).exists()
