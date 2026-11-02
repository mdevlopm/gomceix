# Gomceix Flatpak

App id `io.github.mdevlopm.Gomceix`, GNOME 51 runtime (it ships GTK 4.24,
libadwaita 1.10, PyGObject, Python 3.14 and `libwebkit2gtk-4.1`, which the Store
download tool needs for the Microsoft sign-in).

## Build

Prerequisites: `flatpak-builder` (or `flatpak install --user flathub org.flatpak.Builder`)
and the runtime/SDK: `flatpak install --user flathub org.gnome.Platform//51 org.gnome.Sdk//51`.

```bash
packaging/flatpak/build-bundle.sh      # writes dist/Gomceix-<version>-x86_64.flatpak
```

Do the build on a normal Linux filesystem for the builder state (the script uses
`~/flatpak-build`; set `GOMCEIX_FLATPAK_BUILD` to change it). The project may
sit on exFAT, which only matters for the state directory.

The script runs, in essence:

```bash
cd packaging/flatpak
flatpak-builder --user --force-clean --disable-rofiles-fuse \
  --state-dir=~/flatpak-build/state --repo=~/flatpak-build/repo \
  ~/flatpak-build/build io.github.mdevlopm.Gomceix.yml
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  ~/flatpak-build/repo dist/Gomceix-0.1.1-x86_64.flatpak io.github.mdevlopm.Gomceix
```

## Install, run, uninstall

```bash
flatpak install --user dist/Gomceix-0.1.1-x86_64.flatpak
flatpak run io.github.mdevlopm.Gomceix            # or: ... gomceix doctor
flatpak uninstall --user io.github.mdevlopm.Gomceix
flatpak uninstall --user --delete-data io.github.mdevlopm.Gomceix   # also removes ~/.var/app/<id>
```

All user data lives in `~/.var/app/io.github.mdevlopm.Gomceix/` (game data in
`data/gomceix`, settings in `config`).

## What is built from where

* The app is installed with `pip install --no-index --no-build-isolation .`
  from the working tree (`type: dir` source), using the SDK's setuptools.
* Python dependencies (`cryptography`, `cffi`, `pycparser`, `python-xlib`,
  `six`) are hash-pinned PyPI wheels in the `python3-dependencies` module; the
  build runs with the network disabled. To refresh them:

  ```bash
  python3 packaging/flatpak/update-python-deps.py     # prints `sources:` entries
  ```

  and paste the output over the sources of `python3-dependencies`. If the
  runtime's Python minor version changes, also change the `python3.14` paths and
  `PYTAG` in the script.
* `gomceix/core/{injector,fullscreen-nudge,desktop-bridge}.exe` are the
  committed mingw cross-compiled helpers (sources in `src/`). mingw is not in
  the Flatpak SDK, so the build uses them as they are and **fails** if one is
  missing, empty or not a PE file. Rebuild them on a host with mingw before
  building if `src/*.c` changed.
* `py7zr` (optional, OptiScaler archives only) and `xrandr` are not shipped; the
  launcher falls back to libXrandr and reports the missing 7-Zip tool itself.

## Flathub notes

`flatpak-builder-lint` currently reports: `metainfo-missing-screenshots` (no
hosted screenshots exist yet) and the informational
`finish-args-contains-both-x11-and-wayland` (intended: the game needs X11, the
launcher uses Wayland). Flathub also wants `cryptography` built
from source (Rust SDK extension + vendored crates) instead of a wheel.
