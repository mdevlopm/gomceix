"""Every file the launcher reads at run time must be inside the wheel.

``locales/*.json`` and ``ui/backgrounds/*.svg`` were once missing from
``[tool.setuptools]``: the source tree worked, the installed copy had no
translations and no backgrounds, and nothing noticed.  Two layers guard that:

* a static check that walks ``gomceix/`` and compares it with the
  ``package-data`` globs and the package discovery rules of ``pyproject.toml``;
* when setuptools is importable, a real wheel build in a temporary directory
  whose member list is compared with the tree.
"""
# SPDX-License-Identifier: MIT

import ast
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:                       # Python 3.10
    tomllib = None

try:
    import setuptools
except ImportError:
    setuptools = None

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "gomceix"
# Never shipped: caches and editor / download leftovers.
IGNORED = re.compile(r"(^|/)(__pycache__|\.pytest_cache)(/|$)|\.py[co]$|\.part$"
                     r"|\.gomceix-orig$|~$")
HELPERS = ("injector.exe", "fullscreen-nudge.exe", "desktop-bridge.exe")


def tree_files():
    """Every file under gomceix/, relative to the project root, as posix."""
    return sorted(
        p.relative_to(ROOT).as_posix() for p in PACKAGE.rglob("*")
        if p.is_file() and not IGNORED.search(p.relative_to(ROOT).as_posix()))


def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))


def _package_dirs():
    """Directories that hold Python modules, relative to the root."""
    return sorted({p.parent.relative_to(ROOT).as_posix()
                   for p in PACKAGE.rglob("*.py")
                   if not IGNORED.search(p.relative_to(ROOT).as_posix())})


@unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
class StaticCoverageTests(unittest.TestCase):
    def setUp(self):
        self.config = pyproject()
        self.package_data = self.config["tool"]["setuptools"]["package-data"]

    def test_every_directory_with_modules_is_a_package(self):
        # find_packages(namespaces=false) skips a directory without __init__.py
        # and so silently drops every module in it.
        missing = [d for d in _package_dirs()
                   if not (ROOT / d / "__init__.py").is_file()]
        self.assertEqual(missing, [], "no __init__.py, left out of the wheel")

    def test_packages_are_discovered_by_find(self):
        find = self.config["tool"]["setuptools"].get("packages")
        self.assertIsInstance(find, dict, "[tool.setuptools.packages.find] "
                              "replaces a hand-kept package list")
        self.assertIn("gomceix.*", find["find"]["include"])
        self.assertIs(find["find"].get("namespaces"), False)

    def test_every_data_file_matches_a_package_data_glob(self):
        covered = set()
        for package, patterns in self.package_data.items():
            base = ROOT / package.replace(".", "/")
            for pattern in patterns:
                covered.update(p.relative_to(ROOT).as_posix()
                               for p in base.glob(pattern) if p.is_file())
        data = [f for f in tree_files() if not f.endswith(".py")]
        orphans = [f for f in data if f not in covered]
        self.assertEqual(orphans, [], "data files not named by "
                         "[tool.setuptools.package-data]")

    def test_package_data_globs_match_something(self):
        for package, patterns in self.package_data.items():
            base = ROOT / package.replace(".", "/")
            for pattern in patterns:
                self.assertTrue(any(base.glob(pattern)),
                                f"{package}: {pattern} matches nothing")

    def test_helper_programs_exist(self):
        for name in HELPERS:
            path = PACKAGE / "core" / name
            self.assertTrue(path.is_file(), f"{name}: run "
                            "scripts/build-helpers.sh before packaging")
            head = path.read_bytes()[:2]
            self.assertEqual(head, b"MZ", f"{name} is not a Windows program")

    def test_version_has_one_source(self):
        dynamic = self.config["tool"]["setuptools"]["dynamic"]["version"]
        self.assertEqual(dynamic, {"attr": "gomceix.__version__"})
        self.assertIn("version", self.config["project"]["dynamic"])
        self.assertNotIn("version", self.config["project"])
        tree = ast.parse((PACKAGE / "__init__.py").read_text("utf-8"))
        assigned = [n for n in tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "__version__"
                            for t in n.targets)]
        self.assertEqual(len(assigned), 1)
        self.assertIsInstance(ast.literal_eval(assigned[0].value), str)

    def test_console_script_target_exists(self):
        target = self.config["project"]["scripts"]["gomceix"]
        module, _, func = target.partition(":")
        source = (ROOT / (module.replace(".", "/") + ".py")).read_text("utf-8")
        self.assertIn(f"def {func}(", source)

    def test_runtime_data_locations_are_declared(self):
        # The code reads these relative to its own module (Path(__file__)).
        for relative in ("locales", "ui/themes", "ui/backgrounds",
                         "ui/style.css"):
            self.assertTrue((PACKAGE / relative).exists(), relative)


@unittest.skipIf(tomllib is None or setuptools is None,
                 "needs tomllib and setuptools")
class WheelContentTests(unittest.TestCase):
    """Build a wheel from a copy of the tree and compare it with the tree."""

    @classmethod
    def setUpClass(cls):
        import shutil
        cls._tmp = tempfile.TemporaryDirectory(prefix="gomceix-wheel-")
        work = Path(cls._tmp.name) / "src"
        work.mkdir()
        shutil.copytree(PACKAGE, work / "gomceix",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
            if (ROOT / name).is_file():
                shutil.copy2(ROOT / name, work / name)
        out = Path(cls._tmp.name) / "out"
        out.mkdir()
        code = ("from setuptools import build_meta; "
                f"print(build_meta.build_wheel({str(out)!r}))")
        result = subprocess.run([sys.executable, "-c", code], cwd=work,
                                text=True, capture_output=True, timeout=300)
        if result.returncode:
            raise AssertionError("wheel build failed:\n" + result.stderr[-3000:])
        cls.wheel = out / result.stdout.strip().splitlines()[-1]
        with zipfile.ZipFile(cls.wheel) as archive:
            cls.names = set(archive.namelist())
            meta = next(n for n in cls.names if n.endswith(".dist-info/METADATA"))
            cls.metadata = archive.read(meta).decode("utf-8")
            entry = next(n for n in cls.names
                         if n.endswith(".dist-info/entry_points.txt"))
            cls.entry_points = archive.read(entry).decode("utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_file_of_the_tree_is_in_the_wheel(self):
        missing = [f for f in tree_files() if f not in self.names]
        self.assertEqual(missing, [], "in the tree, not in the wheel")

    def test_the_wheel_has_nothing_that_is_not_in_the_tree(self):
        runtime = [n for n in self.names if not n.endswith("/")
                   and ".dist-info/" not in n]
        stray = [n for n in runtime if not (ROOT / n).is_file()]
        self.assertEqual(stray, [])

    def test_version_comes_from_the_package(self):
        sys.path.insert(0, str(ROOT))
        try:
            from gomceix import __version__
        finally:
            sys.path.remove(str(ROOT))
        self.assertIn(f"\nVersion: {__version__}\n", self.metadata)
        self.assertIn(f"-{__version__}-", self.wheel.name)

    def test_console_script_is_registered(self):
        self.assertIn("gomceix = gomceix.core.__main__:main", self.entry_points)

    def test_dependencies_are_declared(self):
        for dep in ("cryptography", "python-xlib"):
            self.assertRegex(self.metadata, rf"Requires-Dist: {dep}\b")


class RepositoryUrlTests(unittest.TestCase):
    """One public repository: the update check, the project links, the
    AppStream page and the Flatpak recipe must all name the same one."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        try:
            from gomceix.core import config
        finally:
            sys.path.remove(str(ROOT))
        self.config = config

    def test_site_url_is_the_self_update_repository(self):
        self.assertEqual(self.config.SITE_URL,
                         f"https://github.com/{self.config.SELF_REPO}")

    def test_no_published_file_names_another_repository(self):
        own = self.config.SELF_REPO
        files = [ROOT / "pyproject.toml",
                 *(ROOT / "data").glob("*.metainfo.xml"),
                 *(ROOT / "packaging" / "flatpak").glob("*.yml")]
        for path in files:
            for repo in re.findall(r"github\.com/(mdevlopm/[\w.-]+)",
                                   path.read_text()):
                self.assertEqual(repo, own, f"{path.name} names {repo}")


if __name__ == "__main__":
    unittest.main()
