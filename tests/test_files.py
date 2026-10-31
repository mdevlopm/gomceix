"""Keeping a user's background image: validation and the private copy."""
import pytest

from gomceix.ui import files


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "gomceix"


def test_a_valid_image_is_copied_into_the_app_data_dir(tmp_path, data_home):
    src = tmp_path / "Wall Paper.PNG"
    src.write_bytes(b"png")
    kept = files.store_background(src)
    assert kept == str(data_home / "background.png")
    assert (data_home / "background.png").read_bytes() == b"png"
    src.unlink()                                   # the original may disappear
    assert (data_home / "background.png").exists()


def test_a_new_choice_replaces_the_old_copy(tmp_path, data_home):
    a, b = tmp_path / "a.png", tmp_path / "b.jpg"
    a.write_bytes(b"1")
    b.write_bytes(b"2")
    files.store_background(a)
    files.store_background(b)
    assert sorted(p.name for p in data_home.iterdir()) == ["background.jpg"]


@pytest.mark.parametrize("name", ["notes.txt", "archive.zip", "noext"])
def test_other_file_types_are_refused(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    with pytest.raises(files.ImageError):
        files.store_background(f)


def test_missing_and_oversized_files_are_refused(tmp_path, monkeypatch):
    with pytest.raises(files.ImageError):
        files.store_background(tmp_path / "gone.png")
    big = tmp_path / "big.png"
    big.write_bytes(b"12345")
    monkeypatch.setattr(files, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(files.ImageError):
        files.store_background(big)


def test_every_data_directory_is_listed_as_package_data():
    tomllib = pytest.importorskip("tomllib")          # Python 3.11+
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    listed = {(pkg, pat) for pkg, pats in data.items() for pat in pats}
    assert ("gomceix", "locales/*.json") in listed
    assert {("gomceix.ui", "themes/*.json"), ("gomceix.ui", "backgrounds/*.svg")} <= listed
