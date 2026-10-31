#!/usr/bin/env bash
# Install a built wheel into a brand-new virtual environment and exercise the
# INSTALLED copy, never the source tree.
#
#   scripts/smoke-installed.sh [WHEEL] [--keep] [--no-gui]
#
# WHEEL defaults to the newest dist/gomceix-*.whl. Everything runs with a
# throw-away HOME / XDG_* (your real ones are never read or written), from an
# unrelated working directory, with PYTHONPATH unset. Steps: pip install,
# `gomceix doctor`, `python -I -m gomceix doctor`, then (when dbus-run-session
# and mutter exist, and --no-gui is not given) packaging/python/smoke_gui.py
# inside a headless mutter.
# Needs the system GTK 4 / libadwaita / PyGObject packages (docs/install.md).
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
wheel=
keep=0 gui=1
for arg in "$@"; do
    case $arg in
        --keep) keep=1 ;;
        --no-gui) gui=0 ;;
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) wheel=$arg ;;
    esac
done
if [ -z "$wheel" ]; then
    wheel=$(find "$root/dist" -maxdepth 1 -name 'gomceix-*.whl' 2>/dev/null | sort | tail -n 1)
fi
[ -f "$wheel" ] || { echo "no wheel found: build one with scripts/build-dist.sh" >&2; exit 1; }
wheel=$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")

work=$(mktemp -d)
cleanup() { if [ "$keep" = 1 ]; then echo "kept: $work"; else rm -rf "$work"; fi; }
trap cleanup EXIT

venv=$work/venv
mkdir -p "$work/home" "$work/cwd"
python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip --disable-pip-version-check install --quiet "$wheel"

env_clean=(env -u PYTHONPATH -u GOMCEIX_HOME
    "HOME=$work/home" "XDG_DATA_HOME=$work/home/.local/share"
    "XDG_CONFIG_HOME=$work/home/.config" "XDG_CACHE_HOME=$work/home/.cache"
    "XDG_STATE_HOME=$work/home/.local/state")

cd "$work/cwd"
echo "== installed package"
"${env_clean[@]}" "$venv/bin/python" -I -c \
    'import gomceix, sys; print(gomceix.__file__, gomceix.__version__)' \
    | tee "$work/where.txt"
grep -q "^$venv/" "$work/where.txt" || { echo "FAIL: not imported from the venv" >&2; exit 1; }

echo "== gomceix doctor (console script)"
"${env_clean[@]}" "$venv/bin/gomceix" doctor | head -n 3
echo "== python -I -m gomceix doctor"
"${env_clean[@]}" "$venv/bin/python" -I -m gomceix doctor | head -n 1

if [ "$gui" = 1 ] && command -v dbus-run-session >/dev/null 2>&1 && command -v mutter >/dev/null 2>&1; then
    echo "== headless GUI smoke test"
    status=0
    "${env_clean[@]}" GOMCEIX_SMOKE_PREFIX="$venv" GOMCEIX_DEMO=1 \
        GSK_RENDERER=cairo GTK_A11Y=none GDK_BACKEND=wayland \
        dbus-run-session -- mutter --headless --wayland --no-x11 \
        --virtual-monitor 1200x900 -- \
        "$venv/bin/python" -I "$root/packaging/python/smoke_gui.py" \
        >"$work/gui.log" 2>&1 || status=$?
    grep -vE 'dconf|portal|AT-SPI|a11y|-WARNING|-CRITICAL|-Message|dbus-daemon|fusermount3|^\*\* Message|connection to the bus|^$' "$work/gui.log" || true
    # mutter may not pass the program's exit status on; the success line decides.
    if [ "$status" != 0 ] || ! grep -q '^SMOKE OK' "$work/gui.log"; then
        echo "FAIL: GUI smoke test (exit $status); full log:" >&2
        cat "$work/gui.log" >&2
        exit 1
    fi
else
    echo "== skipped GUI smoke test (--no-gui, or dbus-run-session / mutter missing)"
fi
