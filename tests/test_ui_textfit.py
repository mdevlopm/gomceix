from gomceix.ui.textfit import VERSION_SIZE_CLASSES, version_size_class


def test_a_short_version_keeps_the_big_banner_number():
    assert version_size_class("26.52") == "" and version_size_class("") == "" and version_size_class(None) == ""


def test_longer_labels_get_smaller_steps_and_never_stay_at_full_size():
    sizes = [version_size_class(t) for t in ("26.60.20", "26.60.20.7", "26.100.123.7-preview", "x" * 80)]
    assert sizes == ["gx-version-md", "gx-version-sm", "gx-version-xs", "gx-version-xs"]
    assert set(sizes) <= set(VERSION_SIZE_CLASSES)


def test_every_size_class_exists_in_the_stylesheet():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "gomceix/ui/style.css").read_text(encoding="utf-8")
    assert all(name in css for name in VERSION_SIZE_CLASSES)
