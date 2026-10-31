#!/usr/bin/env python3
"""Print the `sources:` entries of the python3-dependencies module.

Usage:  python3 update-python-deps.py [name==version ...]

With no arguments it resolves the newest release of every package below. For
each one it picks a file from the PyPI JSON API that installs on the runtime's
Python (3.14, x86_64, glibc): the pure wheel if there is one, else the
manylinux wheel for cp314 or the oldest-glibc abi3 wheel. The output is YAML to
paste into io.github.mdevlopm.Gomceix.yml (url + sha256, nothing unpinned).

Network is needed here, not in the Flatpak build.
"""
import json
import sys
import urllib.request

# Direct dependencies of gomceix (pyproject.toml) and their runtime closure.
PACKAGES = ["cryptography", "cffi", "pycparser", "python-xlib", "six"]
PYTAG = "cp314"


def pick(files):
    pure = [f for f in files if f["filename"].endswith("none-any.whl")]
    if pure:
        return pure[0]
    wheels = [f for f in files if f["filename"].endswith(".whl")
              and "x86_64" in f["filename"] and "manylinux" in f["filename"]
              and "abi3t" not in f["filename"]]
    exact = [f for f in wheels if f"-{PYTAG}-{PYTAG}-" in f["filename"]]
    if exact:
        return exact[0]
    abi3 = sorted((f for f in wheels if "abi3" in f["filename"]),
                  key=lambda f: ("cp39-abi3" not in f["filename"],
                                 "manylinux_2_28" not in f["filename"],
                                 f["filename"]))
    if abi3:
        return abi3[0]
    raise SystemExit("no installable wheel found among: "
                     + ", ".join(f["filename"] for f in files))


def main(argv):
    wanted = dict(a.split("==", 1) for a in argv) if argv else {}
    for name in (list(wanted) or PACKAGES):
        url = f"https://pypi.org/pypi/{name}/" + (
            f"{wanted[name]}/" if name in wanted else "") + "json"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
        chosen = pick(data["urls"])
        print(f"      - type: file\n        url: {chosen['url']}\n"
              f"        sha256: {chosen['digests']['sha256']}")


if __name__ == "__main__":
    main(sys.argv[1:])
