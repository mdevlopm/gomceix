#!/usr/bin/env python3
"""Headless smoke test of an INSTALLED Gomceix (run it with the venv's python).

    GOMCEIX_SMOKE_PREFIX=<venv dir> GOMCEIX_DEMO=1 GSK_RENDERER=cairo \
    GTK_A11Y=none python -I smoke_gui.py

It fails unless the imported package really lives under GOMCEIX_SMOKE_PREFIX
(so a source checkout on sys.path cannot make a broken wheel look fine), then
checks that the data files made it into the install (translations, themes,
backgrounds, style sheet, helper programs), starts the real Application, waits
about three seconds, checks that every sidebar page has been built, rebuilds
each page once, and quits. Needs a display; scripts/smoke-installed.sh runs it
inside a headless mutter.
"""
# SPDX-License-Identifier: MIT
import os
import pkgutil
import sys
from pathlib import Path

prefix = Path(os.environ["GOMCEIX_SMOKE_PREFIX"]).resolve()

import gomceix  # noqa: E402

where = Path(gomceix.__file__).resolve()
if prefix not in where.parents:
    sys.exit(f"FAIL gomceix was imported from {where}, not from {prefix}")
print("package :", where.parent, gomceix.__version__)

from gomceix import i18n  # noqa: E402
from gomceix.ui import theme  # noqa: E402

failures = []

def check(ok, what):
    print(("ok      " if ok else "FAIL    ") + what)
    if not ok:
        failures.append(what)

# --- translations
for code in i18n.LANGUAGES:
    if code == i18n.SOURCE:
        continue
    catalog = i18n.load_catalog(code)
    check(len(catalog) > 100, f"locale {code}: {len(catalog)} strings")
i18n.set_language("tr")
check(i18n._("Play") != "Play" or len(i18n._catalog) > 100, "switching to Turkish loads its catalog")
i18n.set_language("en")

# --- themes, backgrounds, style sheet
themes, problems = theme.discover()
builtin = sorted(p.stem for p in theme.BUILTIN_DIR.glob("*.json"))
check(len(builtin) >= 7, f"{len(builtin)} built-in theme files in the install")
check(set(builtin) <= set(themes), "every built-in theme loads")
check(problems == [], f"no theme problems {problems}")
backgrounds = sorted(p.name for p in theme.BACKGROUNDS_DIR.glob("*.svg"))
check(len(backgrounds) >= 3, f"backgrounds {backgrounds}")
check(Path(theme.__file__).with_name("style.css").is_file(), "ui/style.css")

# --- helper programs the launcher extracts at run time
for name in ("injector.exe", "fullscreen-nudge.exe", "desktop-bridge.exe"):
    blob = pkgutil.get_data("gomceix.core", name)
    check(bool(blob) and blob[:2] == b"MZ", f"helper {name} ({len(blob or b'')} bytes)")

if failures:
    sys.exit("FAIL data files: " + "; ".join(failures))

# --- the window
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from gomceix.ui.app import Application  # noqa: E402

result = {}


def inspect(win):
    rows = []
    index = 0
    while (row := win.nav.get_row_at_index(index)) is not None:
        rows.append(row.page_id)
        index += 1
    result["pages"] = rows
    missing = [pid for pid in rows if win.stack.get_child_by_name(pid) is None]
    result["missing"] = missing
    for pid in rows:
        win.refresh_page(pid)
    result["refreshed"] = True
    result["css"] = app.themes._base_provider is not None
    app.quit()
    return False


def on_window(win):
    GLib.timeout_add(3000, inspect, win)


def watchdog():
    print("FAIL window smoke test timed out")
    os._exit(2)


GLib.timeout_add_seconds(40, watchdog)
app = Application(on_window=on_window)
code = app.run([])
print("pages   :", result.get("pages"))
ok = bool(result.get("pages")) and not result.get("missing") \
    and result.get("refreshed") and result.get("css") and code == 0
print("SMOKE OK" if ok else f"FAIL window: {result} exit={code}")
sys.exit(0 if ok else 1)
