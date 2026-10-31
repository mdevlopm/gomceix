#!/usr/bin/env bash
# Install Gomceix for the current user, without root and without touching the
# system Python.
#
#   scripts/install-user.sh [--prefix DIR] [--wheel FILE] [--python PYTHON]
#                           [--force] [--dry-run] [--uninstall]
#
# What it creates (default prefix ~/.local):
#   PREFIX/share/gomceix-app/venv/        private virtual environment, created with
#                                         --system-site-packages so the system's
#                                         PyGObject / GTK 4 / libadwaita are visible
#   PREFIX/bin/gomceix                    launcher script
#   PREFIX/share/applications/<id>.desktop, share/icons/hicolor/..., share/metainfo/...
#   PREFIX/share/gomceix-app/install-manifest.txt   every path created, with checksum
#   PREFIX/share/gomceix-app/uninstall.sh           copy of uninstall-user.sh
#
# Your game data (~/.local/share/gomceix, ~/.config/gomceix) is never touched.
# Re-running upgrades in place. GTK 4, libadwaita and PyGObject are NOT installed
# here: they come from the distribution (see docs/install.md).
#
#   --prefix DIR     install under DIR instead of ~/.local
#   --wheel FILE     install this wheel instead of building from this checkout
#   --python PYTHON  interpreter for the venv (default python3; needs >= 3.10)
#   --force          replace an existing PREFIX/bin/gomceix that is not ours
#   --dry-run        print what would be done, change nothing
#   --uninstall      run scripts/uninstall-user.sh with the same --prefix
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)

prefix=${HOME:-}/.local
wheel=
python=python3
force=0 dry=0 uninstall=0

die() { echo "error: $*" >&2; exit 1; }
say() { if [ "$dry" = 1 ]; then echo "[dry-run] $*"; else echo "$*"; fi; }

while [ $# -gt 0 ]; do
    case $1 in
        --prefix) shift; [ $# -gt 0 ] || die "--prefix needs a directory"; prefix=$1 ;;
        --wheel) shift; [ $# -gt 0 ] || die "--wheel needs a file"; wheel=$1 ;;
        --python) shift; [ $# -gt 0 ] || die "--python needs a command"; python=$1 ;;
        --force) force=1 ;;
        --dry-run) dry=1 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done

[ "$(id -u)" != 0 ] || die "refusing to run as root: this installs for one user, into $prefix. Run it as your normal user, without sudo."
[ -n "${HOME:-}" ] || die "HOME is not set"
case $prefix in /*) ;; *) prefix=$PWD/$prefix ;; esac
prefix=${prefix%/}

if [ "$uninstall" = 1 ]; then
    args=(--prefix "$prefix")
    if [ "$dry" = 1 ]; then args+=(--dry-run); fi
    exec bash "$here/uninstall-user.sh" "${args[@]}"
fi

app=$prefix/share/gomceix-app
venv=$app/venv
bin=$prefix/bin
apps=$prefix/share/applications
manifest=$app/install-manifest.txt
launcher=$bin/gomceix

# ---- inputs --------------------------------------------------------------
[ -d "$root/data" ] || die "$root/data not found: run this from a checkout or an unpacked source archive"
desktop_src='' metainfo_src=''
for f in "$root"/data/*.desktop; do [ -f "$f" ] && { desktop_src=$f; break; }; done
for f in "$root"/data/*.metainfo.xml; do [ -f "$f" ] && { metainfo_src=$f; break; }; done
[ -n "$desktop_src" ] || die "no .desktop file in $root/data"
[ -z "$wheel" ] || [ -f "$wheel" ] || die "wheel not found: $wheel"
[ -n "$wheel" ] || [ -f "$root/pyproject.toml" ] || die "no pyproject.toml in $root and no --wheel given"

command -v "$python" >/dev/null 2>&1 || die "$python not found"
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "$python is older than 3.10"
"$python" -c 'import venv, ensurepip' 2>/dev/null || die "the venv module is missing: install your distribution's python3-venv (Debian/Ubuntu: sudo apt install python3-venv)"
if ! "$python" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
    echo "warning: $python cannot load GTK 4 / libadwaita through PyGObject." >&2
    echo "         The window will not open until you install them (docs/install.md);" >&2
    echo "         'gomceix play' does not need them." >&2
fi

desktop_id=$(basename "$desktop_src" .desktop)

# ---- tracking ------------------------------------------------------------
declare -a m_files=() m_dirs=()
declare -A m_seen_dirs=() dry_made=()

# What an earlier run created: its directories stay ours, and so do the files
# and caches this run does not write again.
declare -A old_entries=()
if [ -f "$manifest" ]; then
    while IFS=$'\t' read -r kind a b; do
        case $kind in
            dir) m_seen_dirs[$b]=1; m_dirs+=("$b") ;;
            file|cache) old_entries[$b]="$kind"$'\t'"$a" ;;
        esac
    done <"$manifest"
fi

sha() { sha256sum "$1" | cut -d' ' -f1; }

owned() {   # is $1 listed in the existing manifest?
    [ -f "$manifest" ] && awk -F'\t' -v p="$1" '$1=="file" && $3==p {f=1} END {exit !f}' "$manifest"
}

mkdir_tracked() {   # mkdir -p, remembering which levels did not exist
    local target=$1 missing=() d=$1
    while [ ! -d "$d" ]; do missing=("$d" "${missing[@]+"${missing[@]}"}"); d=$(dirname "$d"); done
    for d in ${missing[@]+"${missing[@]}"}; do
        if [ "$dry" = 0 ]; then mkdir "$d"
        elif [ -z "${dry_made[$d]:-}" ]; then say "mkdir $d"; dry_made[$d]=1; fi
        if [ -z "${m_seen_dirs[$d]:-}" ]; then m_seen_dirs[$d]=1; m_dirs+=("$d"); fi
    done
    [ -d "$target" ] || [ "$dry" = 1 ] || die "cannot create $target"
}

place() {   # place SRC DST: copy a file, or refuse to overwrite a foreign one
    local src=$1 dst=$2
    if [ -e "$dst" ] && ! owned "$dst" && ! cmp -s "$src" "$dst"; then
        if [ "$force" = 1 ]; then say "replace foreign $dst (--force)"
        else die "$dst exists and was not installed by this script (use --force to replace it)"; fi
    fi
    mkdir_tracked "$(dirname "$dst")"
    say "install $dst"
    if [ "$dry" = 0 ]; then
        local tmp
        tmp=$(mktemp "$dst.XXXXXX")
        cat "$src" >"$tmp"
        chmod 644 "$tmp"
        mv -f "$tmp" "$dst"
    fi
    m_files+=("file"$'\t'"$(sha "$src")"$'\t'"$dst")
}

manifest_done=0
write_manifest() {
    local tmp d f path
    declare -A written=()
    [ -d "$app" ] || return 0
    tmp=$(mktemp "$manifest.XXXXXX")
    {
        echo "# Gomceix user installation; paths created by scripts/install-user.sh"
        echo "# kind<TAB>sha256 or -<TAB>path"
        for d in ${m_dirs[@]+"${m_dirs[@]}"}; do printf 'dir\t-\t%s\n' "$d"; done
        printf 'venv\t-\t%s\n' "$venv"
        for f in ${m_files[@]+"${m_files[@]}"}; do printf '%s\n' "$f"; written[${f##*$'\t'}]=1; done
        # Entries of an earlier run that this run did not write again.
        while IFS= read -r -d '' path; do
            [ -n "$path" ] && [ -z "${written[$path]:-}" ] || continue
            [ -e "$path" ] || continue
            printf '%s\t%s\n' "${old_entries[$path]}" "$path"
        done < <(if [ "${#old_entries[@]}" -gt 0 ]; then printf '%s\0' "${!old_entries[@]}" | sort -z; fi)
    } >"$tmp"
    mv -f "$tmp" "$manifest"
}

shq() { printf "'%s'" "${1//\'/\'\\\'\'}"; }

work='' tmp_desktop=''
cleanup() {
    local status=$?
    [ -z "$tmp_desktop" ] || rm -f "$tmp_desktop"
    [ -z "$work" ] || rm -rf "$work"
    # A failed run still records what it created, so uninstall-user.sh can undo it.
    if [ "$status" != 0 ] && [ "$dry" = 0 ] && [ "$manifest_done" = 0 ]; then
        write_manifest 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ---- plan and preflight: nothing is changed until every target is checked -----
exec_path=$launcher
case $exec_path in *[\ \"\'\\\`\$]*) exec_path=\"${exec_path//\\/\\\\}\" ;; esac
tmp_desktop=$(mktemp)
awk -v exec_path="$exec_path" '
    /^Exec=gomceix([ \t]|$)/ { $0 = "Exec=" exec_path substr($0, length("Exec=gomceix") + 1) }
    { print }' "$desktop_src" >"$tmp_desktop"

declare -a plan=()   # "source<TAB>destination"
plan+=("$tmp_desktop"$'\t'"$apps/$desktop_id.desktop")
if [ -n "$metainfo_src" ]; then
    plan+=("$metainfo_src"$'\t'"$prefix/share/metainfo/$(basename "$metainfo_src")")
fi
if [ -d "$root/data/icons/hicolor" ]; then
    while IFS= read -r -d '' icon; do
        plan+=("$icon"$'\t'"$prefix/share/icons/hicolor/${icon#"$root"/data/icons/hicolor/}")
    done < <(find "$root/data/icons/hicolor" -type f \( -name '*.svg' -o -name '*.png' \) -print0 | sort -z)
else
    for icon in "$root"/data/icons/*.svg; do
        [ -f "$icon" ] || continue
        plan+=("$icon"$'\t'"$prefix/share/icons/hicolor/scalable/apps/$(basename "$icon")")
    done
fi
plan+=("$here/uninstall-user.sh"$'\t'"$app/uninstall.sh")

foreign() {   # does $1 exist, not from us, and differ from $2?
    [ -e "$1" ] && ! owned "$1" && ! cmp -s "$2" "$1"
}
if [ "$force" = 0 ]; then
    if [ -e "$launcher" ] && ! owned "$launcher"; then
        die "$launcher exists and was not installed by this script (use --force to replace it)"
    fi
    for entry in "${plan[@]}"; do
        if foreign "${entry#*$'\t'}" "${entry%%$'\t'*}"; then
            die "${entry#*$'\t'} exists and was not installed by this script (use --force to replace it)"
        fi
    done
fi

# ---- virtual environment -------------------------------------------------
mkdir_tracked "$app"
# bin/python is a symlink to the system interpreter, so it keeps running after a
# distribution upgrade while the packages sit in lib/pythonX.Y of the old
# version. The environment is reused only when it was made by the interpreter
# that would make it now and pip can still be run in it.
venv_python_minor() {   # major.minor recorded in $venv/pyvenv.cfg
    awk -F' *= *' '$1 == "version" || $1 == "version_info" { split($2, v, "."); print v[1] "." v[2]; exit }' "$venv/pyvenv.cfg" 2>/dev/null
}
want_minor=$("$python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ -x "$venv/bin/python" ] && [ "$(venv_python_minor)" = "$want_minor" ] \
        && "$venv/bin/python" -m pip --version >/dev/null 2>&1; then
    say "reuse virtual environment $venv"
else
    if [ -e "$venv" ]; then say "recreate outdated or broken virtual environment $venv"; [ "$dry" = 1 ] || rm -rf "$venv"; fi
    say "create virtual environment $venv (--system-site-packages)"
    [ "$dry" = 1 ] || "$python" -m venv --system-site-packages "$venv"
fi

if [ "$dry" = 0 ]; then work=$(mktemp -d); fi

if [ -z "$wheel" ]; then
    say "build a wheel from $root"
    if [ "$dry" = 0 ]; then
        # A copy: pip would otherwise write build/ and *.egg-info next to the sources.
        mkdir "$work/tree" "$work/wheel"
        for item in gomceix pyproject.toml README.md LICENSE MANIFEST.in; do
            [ -e "$root/$item" ] && cp -r "$root/$item" "$work/tree/"
        done
        find "$work/tree" -name __pycache__ -type d -prune -exec rm -rf {} +
        "$venv/bin/python" -m pip --disable-pip-version-check wheel --quiet --no-deps --wheel-dir "$work/wheel" "$work/tree"
        wheel=$(find "$work/wheel" -name "gomceix-*.whl" | head -n 1)
    fi
fi
say "pip install ${wheel:-<built wheel>} into the virtual environment"
if [ "$dry" = 0 ]; then
    # Our own package is always replaced, then its dependencies are resolved
    # (already-present system packages count as satisfied).
    "$venv/bin/python" -m pip --disable-pip-version-check install --quiet --force-reinstall --no-deps "$wheel"
    "$venv/bin/python" -m pip --disable-pip-version-check install --quiet "$wheel"
fi

# ---- launcher ------------------------------------------------------------
mkdir_tracked "$bin"
say "write launcher $launcher"
if [ "$dry" = 0 ]; then
    tmp=$(mktemp "$launcher.XXXXXX")
    {
        echo '#!/bin/sh'
        echo '# Generated by Gomceix scripts/install-user.sh; removed by scripts/uninstall-user.sh.'
        echo 'unset PYTHONPATH PYTHONHOME'
        echo "exec $(shq "$venv/bin/gomceix") \"\$@\""
    } >"$tmp"
    chmod 755 "$tmp"
    mv -f "$tmp" "$launcher"
    m_files+=("file"$'\t'"$(sha "$launcher")"$'\t'"$launcher")
else
    m_files+=("file"$'\t'"dry"$'\t'"$launcher")
fi

# ---- desktop integration -------------------------------------------------
for entry in "${plan[@]}"; do
    place "${entry%%$'\t'*}" "${entry#*$'\t'}"
done
if [ "$dry" = 0 ]; then chmod 755 "$app/uninstall.sh"; fi

# ---- caches (best effort) ------------------------------------------------
# A cache the tools create where there was none is ours to remove again.
refresh() {
    local cache=$1; shift
    local existed=0
    [ ! -e "$cache" ] || existed=1
    command -v "$1" >/dev/null 2>&1 || return 0
    say "$*"
    [ "$dry" = 0 ] || return 0
    "$@" >/dev/null 2>&1 || true
    if [ "$existed" = 0 ] && [ -f "$cache" ]; then
        m_files+=("cache"$'\t'"$1"$'\t'"$cache")
    fi
}
refresh "$apps/mimeinfo.cache" update-desktop-database "$apps"
refresh "$prefix/share/icons/hicolor/icon-theme.cache" gtk-update-icon-cache -f -t "$prefix/share/icons/hicolor"

# ---- manifest ------------------------------------------------------------
if [ "$dry" = 0 ]; then write_manifest; manifest_done=1; fi

echo
say "Gomceix installed under $prefix"
case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "note: $bin is not on your PATH; add it, or start Gomceix from your application menu." ;;
esac
echo "start:     gomceix        (or the application menu)"
uninstall_cmd=$(shq "$app/uninstall.sh")
[ "$prefix" = "$HOME/.local" ] || uninstall_cmd="$uninstall_cmd --prefix $(shq "$prefix")"
echo "uninstall: $uninstall_cmd"
