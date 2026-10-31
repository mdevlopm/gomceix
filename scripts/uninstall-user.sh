#!/usr/bin/env bash
# Remove a per-user Gomceix installation made by scripts/install-user.sh.
#
#   scripts/uninstall-user.sh [--prefix DIR] [--dry-run]
#
# Only what the installer recorded in PREFIX/share/gomceix-app/install-manifest.txt
# is removed: the private virtual environment, the launcher, the desktop file, the
# icon, the metainfo, the uninstaller copy, caches the installer created, and the
# directories it had to create (only when they are empty). A file whose contents
# changed since installation is kept and reported.
#
# Your game data and settings are NEVER touched: ~/.local/share/gomceix (the game,
# sign-ins, worlds, downloaded components) and ~/.config/gomceix. Remove those
# yourself (or from the app's Requirements page) if you want them gone too.
#
#   --prefix DIR  the prefix the installer was given (default ~/.local)
#   --dry-run     print what would be removed, change nothing
set -euo pipefail

prefix=${HOME:-}/.local
dry=0

die() { echo "error: $*" >&2; exit 1; }
say() { if [ "$dry" = 1 ]; then echo "[dry-run] $*"; else echo "$*"; fi; }

while [ $# -gt 0 ]; do
    case $1 in
        --prefix) shift; [ $# -gt 0 ] || die "--prefix needs a directory"; prefix=$1 ;;
        --dry-run) dry=1 ;;
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done

[ "$(id -u)" != 0 ] || die "refusing to run as root; run it as the user who installed Gomceix"
[ -n "${HOME:-}" ] || die "HOME is not set"
case $prefix in /*) ;; *) prefix=$PWD/$prefix ;; esac
prefix=${prefix%/}

app=$prefix/share/gomceix-app
manifest=$app/install-manifest.txt

if [ ! -f "$manifest" ]; then
    echo "Nothing to uninstall: $manifest does not exist (wrong --prefix, or not installed with install-user.sh)."
    exit 0
fi

# Paths that hold the user's own data. Nothing at or below them is ever removed.
protected=(
    "${XDG_DATA_HOME:-$HOME/.local/share}/gomceix"
    "$HOME/.local/share/gomceix"
    "${XDG_CONFIG_HOME:-$HOME/.config}/gomceix"
    "$HOME/.config/gomceix"
)
if [ -n "${GOMCEIX_HOME:-}" ]; then protected+=("${GOMCEIX_HOME%/}"); fi

guard_data() {   # refuse anything at or inside the user's own Gomceix data
    local p=$1 q
    case $p in *..*) die "manifest entry with '..', refusing: $p" ;; esac
    for q in "${protected[@]}"; do
        case "$p/" in "$q"/*) die "manifest entry inside your Gomceix data, refusing: $p" ;; esac
    done
}
guard() {   # guard PATH: a file must be inside the prefix and outside user data
    case $1 in "$prefix"/*) ;; *) die "manifest entry outside the prefix, refusing: $1" ;; esac
    guard_data "$1"
}

sha() { sha256sum "$1" | cut -d' ' -f1; }

declare -a dirs=() caches=() files=()
venv=
removed=0 kept=0

# Pass 1: read and validate the whole manifest; nothing is removed yet, so a bad
# entry stops the uninstall before it has touched anything.
while IFS=$'\t' read -r kind a path; do
    case $kind in
        '#'*|'') continue ;;
        dir)
            # Parents of the prefix itself (created on the way) are left alone.
            case $path in "$prefix"|"$prefix"/*) guard_data "$path"; dirs+=("$path") ;; esac ;;
        venv) guard "$path"; venv=$path ;;
        cache) guard "$path"; caches+=("$a"$'\t'"$path") ;;
        file) guard "$path"; files+=("$a"$'\t'"$path") ;;
        *) echo "warning: unknown manifest line: $kind" >&2 ;;
    esac
done <"$manifest"
if [ -n "$venv" ] && [ "$venv" != "$app/venv" ]; then
    die "unexpected virtual environment path in the manifest: $venv"
fi

# Pass 2: remove. A file is removed only when it still has the recorded checksum.
for entry in ${files[@]+"${files[@]}"}; do
    expected=${entry%%$'\t'*} path=${entry#*$'\t'}
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then continue; fi
    if [ -f "$path" ] && [ ! -L "$path" ] && [ "$(sha "$path")" = "$expected" ]; then
        say "remove $path"
        if [ "$dry" = 0 ]; then rm -f -- "$path"; fi
        removed=$((removed + 1))
    else
        echo "keep   $path (changed since installation)"
        kept=$((kept + 1))
    fi
done

if [ -n "$venv" ]; then
    if [ -f "$venv/pyvenv.cfg" ]; then
        say "remove $venv"
        if [ "$dry" = 0 ]; then rm -rf -- "$venv"; fi
        removed=$((removed + 1))
    fi
fi

# The record goes before the directories, which it would keep from being empty.
if [ "$dry" = 0 ]; then rm -f -- "$manifest"; fi

declare -A cache_tool=()
for entry in ${caches[@]+"${caches[@]}"}; do cache_tool[${entry#*$'\t'}]=${entry%%$'\t'*}; done

others_in() {   # entries of directory $1 other than the caches this installer made
    local f
    for f in "$1"/* "$1"/.[!.]*; do
        [ -e "$f" ] || [ -L "$f" ] || continue
        [ -n "${cache_tool[$f]:-}" ] || return 0
    done
    return 1
}

# The directories the installer created, deepest first, only when nothing but
# its own caches is left in them.
for ((i = ${#dirs[@]} - 1; i >= 0; i--)); do
    d=${dirs[i]}
    [ -d "$d" ] || continue
    if others_in "$d"; then continue; fi
    if [ "$dry" = 1 ]; then say "rmdir (if empty) $d"; continue; fi
    for f in "$d"/* "$d"/.[!.]*; do
        if [ -f "$f" ] && [ -n "${cache_tool[$f]:-}" ]; then rm -f -- "$f"; fi
    done
    say "rmdir  $d"
    rmdir -- "$d"
done

# Caches still there sit in a directory that stays: refresh them, or drop them
# when nothing else is in it.
for cache in "${!cache_tool[@]}"; do
    [ -e "$cache" ] || continue
    dir=$(dirname "$cache"); tool=${cache_tool[$cache]}
    if [ "$dry" = 1 ]; then say "refresh or remove cache $cache"
    elif others_in "$dir"; then
        if command -v "$tool" >/dev/null 2>&1; then
            case $tool in
                update-desktop-database) "$tool" "$dir" >/dev/null 2>&1 || true ;;
                *) "$tool" -f -t "$dir" >/dev/null 2>&1 || true ;;
            esac
        fi
    else
        rm -f -- "$cache"
    fi
done

echo
say "Gomceix removed from $prefix ($removed items removed, $kept kept)."
echo "Your game data was not touched: ${XDG_DATA_HOME:-$HOME/.local/share}/gomceix"
