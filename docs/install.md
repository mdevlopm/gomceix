# Installing Gomceix

Gomceix needs Python 3.10 or newer and, for its window, GTK 4, libadwaita 1.5
or newer and PyGObject. Those three come from your distribution; they are not
pip packages. Older releases (Ubuntu 22.04, Debian 12) ship an older libadwaita;
use the Flatpak there.
Everything else (the game engine, Store tools, ...) is downloaded by the app
itself the first time you need it.

Prefer a sandbox? The Flatpak bundles every dependency below; this page is for
installing without it.

## 1. System packages

| Distribution | Install |
|---|---|
| Fedora | `sudo dnf install python3 python3-gobject gtk4 libadwaita python3-cryptography python3-xlib tar curl zstd` |
| Debian / Ubuntu | `sudo apt install python3 python3-venv python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-cryptography python3-xlib tar curl zstd` |
| Arch | `sudo pacman -S python python-gobject gtk4 libadwaita python-cryptography python-xlib tar curl zstd` |
| openSUSE | `sudo zypper install python3 python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 python3-cryptography python3-python-xlib tar curl zstd` |

Optional, for the Microsoft Store sign-in window (Gomceix downloads its own copy
when the system has none): `webkit2gtk4.1` (Fedora), `libwebkit2gtk-4.1-0`
(Debian/Ubuntu), `webkit2gtk-4.1` (Arch), `libwebkit2gtk-4_1-0` (openSUSE).

`cryptography` is needed for Normal-mode sign-in in every install. An installed
copy gets it through pip (the installer and the wheel pull it in as a dependency)
or through the Flatpak runtime. A run from a source checkout needs the package
from the table above, or the launcher installs it with pip when a Normal-mode
launch needs it. `python-xlib` is optional.

Check the result with `python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")'`
(no output means it works) and, once Gomceix is installed, `gomceix doctor`.

## 2. Install for your user (recommended)

From a checkout or an unpacked source archive:

```bash
scripts/install-user.sh
```

It creates a private virtual environment (with access to the system's GTK
bindings) in `~/.local/share/gomceix-app/venv`, a launcher `~/.local/bin/gomceix`,
and the menu entry, icon and AppStream file under `~/.local/share`. It never
uses `sudo`, never touches the system Python, and can be run again to upgrade.

Options: `--prefix DIR` (instead of `~/.local`), `--wheel FILE` (install a
built wheel), `--dry-run` (show what would happen), `--force` (replace a
`~/.local/bin/gomceix` that something else created), `--python PYTHON`.
Make sure `~/.local/bin` is in your `PATH`; the menu entry works either way.

Start it from the application menu, or run `gomceix` (`gomceix gui` is the
same).

### Uninstall

```bash
~/.local/share/gomceix-app/uninstall.sh      # or: scripts/uninstall-user.sh
```

Only the files the installer recorded in
`~/.local/share/gomceix-app/install-manifest.txt` are removed (a file you edited
since is kept and reported). Your game, sign-ins and settings in
`~/.local/share/gomceix` and `~/.config/gomceix` are not touched; see section 5.

## 3. Other ways

* **Wheel with pip**, inside a virtual environment that can see the system GTK
  bindings (a plain `pip install` into a venv without
  `--system-site-packages` cannot import `gi`):

  ```bash
  python3 -m venv --system-site-packages ~/gomceix-venv
  ~/gomceix-venv/bin/pip install gomceix-0.1.1-py3-none-any.whl
  ~/gomceix-venv/bin/gomceix
  ```

  Do not use `pip install --user --break-system-packages`; it mixes the app
  into your system Python.
* **Flatpak**: no release carries a bundle yet. Build it from the source tree
  with `packaging/flatpak/build-bundle.sh` and install it as
  [`packaging/flatpak/README.md`](../packaging/flatpak/README.md) describes.
* **From the source tree**, nothing to install: `python3 -m gomceix`
  (`python3 -m gomceix doctor`, `python3 -m gomceix play`). It reads the same
  data folders as an installed copy.
* **Build the packages yourself**: `scripts/build-dist.sh` (needs
  `pip install build twine`) writes the sdist and wheel to `dist/`. The three
  Windows helper programs in `gomceix/core/*.exe` are built from `src/*.c` by
  `scripts/build-helpers.sh` (needs the mingw-w64 cross compiler, or
  `--container` with podman/docker) and must be in place before building.

## 4. What is downloaded, and where

Gomceix does not contain Minecraft. On first use it downloads, into its own
folder only:

| Component | Used for |
|---|---|
| Game engine (WineGDK build) | runs the game |
| Store download tool | downloads the game with your Microsoft account |
| Store sign-in window | only on systems without a suitable WebKitGTK |
| Online login helper | lets the game sign in online |
| umu launcher | starts the game in a clean runtime |
| Java runtime, ProxyPass | only for ProxyPass mode |
| Python login libraries | the `cryptography` package, only if the system has none and you did not install it as above |
| Download cache | archives kept after installing; safe to delete |

Everything lives under `~/.local/share/gomceix` (`$XDG_DATA_HOME/gomceix`; set
`GOMCEIX_HOME` or use the install location setting to move it). Launcher settings
are in `settings.json` there. `~/.config/gomceix` holds only the window's
preferences (`ui.json`: theme, language, background). Logs are in
`~/.local/share/gomceix/logs`.

## 5. Removing downloaded components and game data

Open the **Requirements** page: every component can be removed on its own and
downloaded again later. To remove everything the app ever stored, delete
`~/.local/share/gomceix` and `~/.config/gomceix` after uninstalling. That also
deletes the game's data, your worlds included. To keep your worlds, copy the
`Users` folder first. It is at
`~/.local/share/gomceix/compatdata/pfx/drive_c/users/steamuser/AppData/Roaming/Minecraft Bedrock/Users/`
(Preview keeps its data in the `Minecraft Bedrock Preview` folder beside it).
The Saves & Content page only lists your worlds; it cannot back them up or
restore them.

Copies the launcher makes itself, for example before a new game version first
opens your data, are in `~/.local/share/gomceix/backups`. To go back to one,
close the game and copy the `Users` folder inside it over the game's own
`Users` folder.

## 6. Troubleshooting

* **"needs GTK 4 and libadwaita"** or `ModuleNotFoundError: gi`: install the
  packages from section 1. In a virtual environment, create it with
  `--system-site-packages`. `gomceix play` does not need GTK.
* **"libadwaita ... is too old"**: the window needs libadwaita 1.5 or newer
  (`gomceix doctor` shows the installed version). Update the distribution or use
  the Flatpak.
* **`gomceix` stopped starting after a system upgrade** (`No module named
  'gomceix'`): the installer's environment belongs to the previous Python. Run
  `scripts/install-user.sh` again; it recreates the environment when the Python
  version changed.
* **`python3 -m venv` fails on Debian/Ubuntu**: `sudo apt install python3-venv`.
* **`gomceix: command not found`**: add `~/.local/bin` to `PATH`, or use the
  menu entry.
* **Checking the installed version**: `gomceix --version` (or `-V`) prints it,
  and `gomceix doctor` prints it on its first line.
* **Run as root / with sudo is refused**: that is deliberate; run as your normal
  user, everything it needs asks for itself.
* **The window opens but looks unstyled or has no translations**: the install is
  incomplete (an old wheel built before locales and themes were packaged);
  reinstall with `scripts/install-user.sh`.
* **Missing `tar`, `curl` or `zstd`** reported by `gomceix doctor`: install them
  with your package manager.
* **No application-menu entry**: log out and in, or run
  `update-desktop-database ~/.local/share/applications`.
