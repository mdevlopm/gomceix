#!/usr/bin/env bash
# Build the Windows helper programs that Gomceix runs inside the game's Wine
# prefix, from src/*.c, with the mingw-w64 cross compiler.
#
#   gomceix/core/injector.exe          src/injector.c           (packaged)
#   gomceix/core/fullscreen-nudge.exe  src/fullscreen-nudge.c   (packaged)
#   gomceix/core/desktop-bridge.exe    src/desktop-bridge.c     (packaged)
#   <out>/cryptbase.dll, xcurl-cashim.dll   only with --all; they are NOT part of
#       the wheel: the launcher downloads them inside the "openssl-xcurl-set"
#       release asset (gomceix/core/fixups.py, ensure_openssl_xcurl_set).
#
# The first three are loaded at run time through pkgutil.get_data("gomceix.core",
# name) and written to the cache directory (gomceix/core/winehelper.py,
# inject.py), so they must sit next to the Python modules, in the source tree,
# BEFORE `python -m build`.
#
# Usage: scripts/build-helpers.sh [--all] [--out DIR] [--check] [--container]
#   --all        also build cryptbase.dll and xcurl-cashim.dll (into build/helpers)
#   --out DIR    where the three packaged helpers go (default: gomceix/core)
#   --check      build nothing; verify the packaged helpers exist and are
#                64-bit Windows executables
#   --container  re-run this script inside a throw-away Fedora container
#                (podman or docker) that has mingw-w64, for hosts without it
# Environment: CC (default x86_64-w64-mingw32-gcc).
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
src=$root/src
out=$root/gomceix/core
extra_out=$root/build/helpers
cc=${CC:-x86_64-w64-mingw32-gcc}
all=0 check=0 container=0

while [ $# -gt 0 ]; do
    case $1 in
        --all) all=1 ;;
        --check) check=1 ;;
        --container) container=1 ;;
        --out) shift; [ $# -gt 0 ] || { echo "--out needs a directory" >&2; exit 2; }
               out=$1 ;;
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# output name : source file
packaged=(
    "injector.exe:injector.c"
    "fullscreen-nudge.exe:fullscreen-nudge.c"
    "desktop-bridge.exe:desktop-bridge.c"
)

# A PE file starts with "MZ"; byte 0x3c points at "PE\0\0"; machine 0x8664 is
# x86-64. Pure shell so it needs neither file(1) nor Python.
is_pe64() {
    local f=$1 magic off machine
    [ -s "$f" ] || return 1
    magic=$(head -c 2 "$f")
    [ "$magic" = "MZ" ] || return 1
    off=$(od -An -t u4 -j 60 -N 4 "$f" | tr -d ' ')
    [ "$(od -An -c -j "$off" -N 2 "$f" | tr -d ' ')" = 'PE' ] || return 1
    machine=$(od -An -t x2 -j $((off + 4)) -N 2 "$f" | tr -d ' ')
    [ "$machine" = 8664 ]
}

if [ "$check" = 1 ]; then
    bad=0
    for entry in "${packaged[@]}"; do
        name=${entry%%:*}
        if is_pe64 "$out/$name"; then
            printf 'ok       %s (%s bytes)\n' "$name" "$(wc -c <"$out/$name")"
        else
            printf 'MISSING  %s (absent or not a 64-bit Windows executable)\n' "$name"
            bad=1
        fi
    done
    exit $bad
fi

if [ "$container" = 1 ]; then
    [ "$out" = "$root/gomceix/core" ] || { echo "--container cannot be combined with --out" >&2; exit 2; }
    engine=$(command -v podman || command -v docker || true)
    [ -n "$engine" ] || { echo "--container needs podman or docker" >&2; exit 1; }
    args=()
    if [ "$all" = 1 ]; then args+=(--all); fi
    # The tree is mounted read-write (:Z relabels it on SELinux hosts); the
    # compiler is installed in the throw-away container, nothing is left behind.
    exec "$engine" run --rm -v "$root:/work:Z" -w /work -e HOME=/tmp \
        registry.fedoraproject.org/fedora:latest bash -c \
        'dnf install -y -q mingw64-gcc >/dev/null && CC=x86_64-w64-mingw32-gcc bash scripts/build-helpers.sh "$@"' \
        _ ${args[@]+"${args[@]}"}
fi

if ! command -v "$cc" >/dev/null 2>&1; then
    cat >&2 <<EOF
error: $cc not found.
Install the mingw-w64 cross compiler:
  Fedora        sudo dnf install mingw64-gcc
  Debian/Ubuntu sudo apt install gcc-mingw-w64-x86-64
  Arch          sudo pacman -S mingw-w64-gcc
  openSUSE      sudo zypper install cross-x86_64-w64-mingw32-gcc
or run: scripts/build-helpers.sh --container   (needs podman or docker)
EOF
    exit 1
fi

mkdir -p "$out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# -s strips symbols; --no-insert-timestamp keeps the PE header free of the build
# time, so rebuilding the same source with the same compiler gives the same bytes.
cflags=(-O2 -municode -s "-Wl,--no-insert-timestamp")

for entry in "${packaged[@]}"; do
    name=${entry%%:*} file=${entry#*:}
    echo "CC  $file -> $name"
    "$cc" "${cflags[@]}" "$src/$file" -o "$tmp/$name"
    is_pe64 "$tmp/$name" || { echo "error: $name is not a 64-bit PE file" >&2; exit 1; }
    cp "$tmp/$name" "$out/$name"
done

if [ "$all" = 1 ]; then
    mkdir -p "$extra_out"
    echo "CC  cryptbase-stub.c -> cryptbase.dll"
    "$cc" -O2 -mrdrnd -shared -s -Wl,--no-insert-timestamp \
        "$src/cryptbase-stub.c" -o "$tmp/cryptbase.dll"
    echo "CC  xcurl-cashim.c -> xcurl-cashim.dll"
    "$cc" -O2 -shared -s -Wl,--no-insert-timestamp \
        "$src/xcurl-cashim.c" -o "$tmp/xcurl-cashim.dll"
    for name in cryptbase.dll xcurl-cashim.dll; do
        is_pe64 "$tmp/$name" || { echo "error: $name is not a 64-bit PE file" >&2; exit 1; }
        cp "$tmp/$name" "$extra_out/$name"
    done
    echo "extra libraries (not packaged): $extra_out"
fi

echo "helpers written to $out"
