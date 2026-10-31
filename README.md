# Gomceix

A GNOME-style launcher for **Minecraft Bedrock Edition** on Linux, built with GTK 4 and libadwaita.

> Early development. The new interface is being built on top of a tested launch/download backend; some pages still show demo data.

## What it does
- Downloads the game from the Microsoft Store with **your own account**, sets everything up and starts it.
- Plays with real Xbox sign-in (friends, servers, Realms). You sign in on the Accounts page, not in the game: the game's own sign-in link is hidden.
- Themes (light, dark, your own JSON themes), a picture behind the Play banner (built-in or your own image), adaptive layout.
- A **Requirements** page lists everything Gomceix downloads for itself (game engine, Store tools, umu, Java and ProxyPass for that mode); each part can be downloaded or removed on its own, and all of it lives in Gomceix's own folder.
- Two modes, switchable on the Play page: **Normal** (the launcher signs the game in with your Microsoft account) and **ProxyPass** (the game starts signed out and a local Java proxy at 127.0.0.1:19132 signs in and forwards you to the server you chose; Java and the ProxyPass jar are downloaded on first use).
- English, Türkçe and 中文 interface, switchable at runtime (Settings ▸ Appearance ▸ Language); more languages are one JSON file each.
- Versions, a list of your worlds, diagnostics (GPU, Wine prefix); profiles from the command line (`gomceix profiles`).

It does **not** contain or distribute Minecraft. You need a Microsoft account that owns the game.

## Modes
- **Normal** needs `python3-cryptography` (the installer and the Flatpak bring it; see [`docs/install.md`](docs/install.md)).
- **ProxyPass** needs a game version that has a ProxyPass build. With **Online mode** on (the default), the version list offers only those versions. With it off, any version starts, and one without a build starts without the proxy. Online mode off joins only servers that do not check accounts.

## Install
Needs Python 3.10+, GTK 4, libadwaita 1.5+ and PyGObject from your distribution (package names for Fedora, Debian/Ubuntu, Arch and openSUSE are in [`docs/install.md`](docs/install.md)).

```bash
scripts/install-user.sh      # per-user install into ~/.local, no root
gomceix                      # or the application menu
~/.local/share/gomceix-app/uninstall.sh
```

Flatpak (you build it from [`packaging/flatpak/`](packaging/flatpak/README.md); no release carries one yet), wheel/pip, what gets downloaded and where, uninstalling and troubleshooting: [`docs/install.md`](docs/install.md).

## Run from source
```bash
python3 -m gomceix          # open the launcher
python3 -m gomceix doctor   # check the system
python3 -m gomceix play     # start the game without the window
```

## Themes
Built-in themes live in `gomceix/ui/themes/` (format: [`docs/themes.md`](docs/themes.md)). Put your own `.json` theme in `~/.local/share/gomceix/themes/`; a theme with the same `id` overrides a built-in one. Invalid files are reported in Settings and never crash the app.

## Tests and packaging
```bash
python3 -m pytest -q
scripts/build-helpers.sh --check   # the bundled Windows helpers are present
scripts/build-dist.sh              # sdist + wheel into dist/ (needs: pip install build twine)
scripts/smoke-installed.sh         # install the wheel in a clean venv and start it headless
```

## License
MIT, see [`LICENSE`](LICENSE), which also says where the downloaded components come from. Not affiliated with or endorsed by Mojang Studios or Microsoft.

## Translating
Add `gomceix/locales/<code>.json` (`{"English text": "translation"}`) and the language to `LANGUAGES` in `gomceix/i18n.py`. `tests/test_i18n_catalog.py` fails when a string is missing, stale or has different `{placeholders}`.
