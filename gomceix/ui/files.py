"""Choosing and keeping a user's image. The checks are pure (no GTK) so they are testable."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from gomceix.i18n import _

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg")
MAX_IMAGE_BYTES = 40 * 1024 * 1024


class ImageError(Exception):
    """The chosen file cannot be used; the message is meant for the user."""


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "gomceix"


def store_background(source) -> str:
    """Validate `source` and keep a private copy; returns the copy's path.

    A copy, because the original may sit on a drive that is not mounted next
    time, or behind a sandbox portal path that disappears.
    """
    src = Path(source)
    if src.suffix.lower() not in IMAGE_EXTS:
        raise ImageError(_("That file is not a supported image (PNG, JPEG, WebP, BMP or SVG)."))
    try:
        if not src.is_file():
            raise ImageError(_("That file could not be found."))
        if src.stat().st_size > MAX_IMAGE_BYTES:
            raise ImageError(_("That image is larger than 40 MB."))
        dest_dir = data_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"background{src.suffix.lower()}"
        fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".tmp-bg-")
        os.close(fd)
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        for old in dest_dir.glob("background.*"):     # one background at a time
            if old != dest:
                try:
                    old.unlink()
                except OSError:
                    pass
    except OSError as exc:
        raise ImageError(_("Could not read the image: {error}", error=exc.strerror or exc)) from exc
    return str(dest)


def pick_image(win, on_chosen, on_cancel=None) -> None:
    """Show the system file chooser. `on_chosen(path)` gets a local file path;
    `on_cancel()` runs when nothing was chosen (also when the chooser failed)."""
    from gi.repository import Gio, GLib, Gtk

    dialog = Gtk.FileDialog(title=_("Choose a background image"), modal=True)
    images = Gtk.FileFilter()
    images.set_name(_("Images"))
    images.add_mime_type("image/*")
    for ext in IMAGE_EXTS:                   # some desktops report no mime type for a file
        images.add_suffix(ext.lstrip("."))
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(images)
    dialog.set_filters(filters)
    dialog.set_default_filter(images)
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    if pictures and os.path.isdir(pictures):
        dialog.set_initial_folder(Gio.File.new_for_path(pictures))

    def done(dlg, result):
        try:
            chosen = dlg.open_finish(result)
        except GLib.Error:                   # dismissed, or no file chooser available
            chosen = None
        path = chosen.get_path() if chosen is not None else None
        if path:
            on_chosen(path)
        elif on_cancel:
            on_cancel()

    dialog.open(win, None, done)
