#!/usr/bin/env bash
# Build the sdist and wheel, check them, and copy them to dist/.
#
#   scripts/build-dist.sh [--out DIR] [--work DIR] [--no-isolation]
#
# The build happens in --work (default: a fresh temporary directory) from a
# copy of the tree, so no build/, *.egg-info or __pycache__ is left in the
# source directory (which may sit on a file system without symlinks, such as
# exFAT). Needs `python -m build` and `twine`: pip install build twine.
# The Windows helpers in gomceix/core must exist (scripts/build-helpers.sh).
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=$root/dist
work=
isolation=()
python=${PYTHON:-python3}

while [ $# -gt 0 ]; do
    case $1 in
        --out) shift; out=$1 ;;
        --work) shift; work=$1 ;;
        --no-isolation) isolation=(--no-isolation) ;;
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

bash "$root/scripts/build-helpers.sh" --check

cleanup=0
if [ -z "$work" ]; then work=$(mktemp -d); cleanup=1; fi
mkdir -p "$work/tree" "$work/dist"
trap '[ "$cleanup" = 1 ] && rm -rf "$work"' EXIT

# Copy only what a source distribution may contain; never agent-work/ or .git/.
for item in gomceix src scripts packaging data docs tests LICENSE README.md \
            pyproject.toml MANIFEST.in pytest.ini; do
    [ -e "$root/$item" ] && cp -r "$root/$item" "$work/tree/"
done
find "$work/tree" -name __pycache__ -type d -prune -exec rm -rf {} +

(cd "$work/tree" && "$python" -m build ${isolation[@]+"${isolation[@]}"} \
    --outdir "$work/dist")
"$python" -m twine check "$work"/dist/*
"$python" "$root/packaging/python/check_dist.py" "$work/dist"

mkdir -p "$out"
cp "$work"/dist/* "$out/"
echo "artifacts in $out:"
ls -l "$out"
