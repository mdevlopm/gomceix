#!/usr/bin/env bash
# Build dist/Gomceix-<version>-x86_64.flatpak from the working tree.
# Needs flatpak-builder (or the org.flatpak.Builder flatpak) and the GNOME 51
# runtime + SDK. Builder state lives outside the project (exFAT has no
# symlinks): override with GOMCEIX_FLATPAK_BUILD=<dir>.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="${GOMCEIX_FLATPAK_BUILD:-$HOME/flatpak-build}"
id=io.github.mdevlopm.Gomceix
version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/gomceix/__init__.py")"

if command -v flatpak-builder >/dev/null; then
  builder=(flatpak-builder)
else
  # Without the documents-portal FUSE mount (sessions that do not run it) the
  # builder's sandbox cannot start; it is not needed for a build.
  portal=()
  [ -d "/run/user/$(id -u)/doc/by-app" ] || portal=(--no-documents-portal)
  builder=(flatpak run --user "${portal[@]}" org.flatpak.Builder)
fi

mkdir -p "$work" "$root/dist"
cd "$here"
"${builder[@]}" --user --force-clean --disable-rofiles-fuse \
  --install-deps-from=flathub \
  --state-dir="$work/state" --repo="$work/repo" "$work/build" "$id.yml"
flatpak build-bundle \
  --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$work/repo" "$root/dist/Gomceix-$version-x86_64.flatpak" "$id"
echo "built $root/dist/Gomceix-$version-x86_64.flatpak"
