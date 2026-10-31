"""A data folder that cannot be written is a plain BolError, never a traceback."""
import errno

import pytest

from gomceix.core import prefix, util
from gomceix.core.log import BolError


def refuse(*_args, **_kwargs):
    raise OSError(errno.EROFS, "Read-only file system")


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(util, "DATA", tmp_path)
    monkeypatch.setattr(util, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(util, "_ensure_xdg_storage", lambda: None)
    monkeypatch.setattr(prefix, "DATA", tmp_path)
    monkeypatch.setattr(prefix, "GAMES", tmp_path / "games")
    return tmp_path


def test_saving_settings_into_a_read_only_folder_says_where_and_why(data, monkeypatch):
    monkeypatch.setattr(util.os, "open", refuse)
    with pytest.raises(BolError) as caught:
        util.save_settings({"a": 1})
    assert str(data) in str(caught.value) and "Read-only file system" in str(caught.value)


def test_settings_still_save_into_a_writable_folder(data):
    util.save_settings({"a": 1})
    assert util.load_settings()["a"] == 1


def test_the_lock_files_of_an_unwritable_folder_are_a_bolerror(data, monkeypatch):
    monkeypatch.setattr(prefix.os, "open", refuse)
    with pytest.raises(BolError) as caught:
        with prefix.shared_assets_lock("start Minecraft", exclusive=True):
            pass
    assert "Cannot write to" in str(caught.value)
    with pytest.raises(BolError):
        with prefix.prefix_operation_lock("start Minecraft"):
            pass


def test_a_data_folder_that_cannot_be_created_is_a_bolerror(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    missing = locked / "gone" / "gomceix"
    monkeypatch.setattr(util, "DATA", missing)
    monkeypatch.setattr(util, "_ensure_xdg_storage", lambda: None)
    monkeypatch.setattr(prefix, "DATA", missing)
    try:
        with pytest.raises(BolError):
            util.mkdirs()
        with pytest.raises(BolError):
            with prefix.prefix_operation_lock("start Minecraft"):
                pass
    finally:
        locked.chmod(0o700)
