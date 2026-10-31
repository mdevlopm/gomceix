#!/usr/bin/env python3
"""Verify a built sdist and wheel against the source tree.

    python packaging/python/check_dist.py DIST_DIR

Fails (exit 1) when the wheel lacks any file under ``gomceix/`` that the
launcher can read at run time (modules, translations, themes, backgrounds,
style.css, the Windows helper programs), when the sdist lacks the sources,
scripts, desktop files and documents it promises in MANIFEST.in, or when the
version in either name differs from ``gomceix.__version__``.
"""
# SPDX-License-Identifier: MIT
import re
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "gomceix"
IGNORED = re.compile(r"(^|/)__pycache__(/|$)|\.py[co]$|\.part$|\.gomceix-orig$")
HELPERS = ("injector.exe", "fullscreen-nudge.exe", "desktop-bridge.exe")
SDIST_EXTRA = [
    "LICENSE", "README.md", "pyproject.toml", "MANIFEST.in",
    "src/injector.c", "src/fullscreen-nudge.c", "src/desktop-bridge.c",
    "src/cryptbase-stub.c", "src/xcurl-cashim.c",
    "scripts/build-helpers.sh", "scripts/install-user.sh",
    "scripts/uninstall-user.sh", "docs/install.md",
    "data/io.github.mdevlopm.Gomceix.desktop",
    "data/io.github.mdevlopm.Gomceix.metainfo.xml",
    "data/icons/io.github.mdevlopm.Gomceix.svg",
    "tests/test_packaging_data.py",
]


def tree_files():
    return sorted(p.relative_to(ROOT).as_posix() for p in PACKAGE.rglob("*")
                  if p.is_file()
                  and not IGNORED.search(p.relative_to(ROOT).as_posix()))


def version():
    text = (PACKAGE / "__init__.py").read_text("utf-8")
    return re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M).group(1)


def main(argv):
    dist = Path(argv[1] if len(argv) > 1 else ROOT / "dist")
    ver = version()
    problems = []
    wheels = sorted(dist.glob("gomceix-*.whl"))
    sdists = sorted(dist.glob("gomceix-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected one wheel and one sdist in {dist}, found "
              f"{len(wheels)} and {len(sdists)}", file=sys.stderr)
        return 1
    wheel, sdist = wheels[0], sdists[0]

    for artifact in (wheel, sdist):
        if f"-{ver}" not in artifact.name:
            problems.append(f"{artifact.name}: not version {ver}")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for rel in tree_files():
            if rel not in names:
                problems.append(f"wheel lacks {rel}")
        for name in HELPERS:
            member = f"gomceix/core/{name}"
            if member in names and archive.read(member)[:2] != b"MZ":
                problems.append(f"wheel: {member} is not a Windows program")
        if not any(n.endswith(".dist-info/licenses/LICENSE") for n in names):
            problems.append("wheel lacks the LICENSE file")
        stray = [n for n in names if re.match(r"(tests|scripts|src|data)/", n)]
        if stray:
            problems.append(f"wheel carries non-runtime files: {stray[:3]}")
        entry = [n for n in names if n.endswith("entry_points.txt")]
        if not entry or b"gomceix.core.__main__:main" not in archive.read(entry[0]):
            problems.append("wheel lacks the gomceix console script")
        print(f"wheel  {wheel.name}: {len(names)} members")

    with tarfile.open(sdist) as archive:
        prefix = sdist.name[:-len(".tar.gz")] + "/"
        members = {m.name[len(prefix):] for m in archive.getmembers()}
        wanted = set(tree_files()) | set(SDIST_EXTRA)
        for rel in sorted(wanted):
            if rel not in members:
                problems.append(f"sdist lacks {rel}")
        leaked = [m for m in members if m.startswith(("agent-work/", ".git/"))]
        if leaked:
            problems.append(f"sdist carries work files: {leaked[:3]}")
        print(f"sdist  {sdist.name}: {len(members)} members")

    for problem in problems:
        print("FAIL", problem, file=sys.stderr)
    if not problems:
        print(f"ok: {len(tree_files())} package files verified in both "
              f"artifacts, version {ver}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
