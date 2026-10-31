"""scripts/install-user.sh and uninstall-user.sh, without network or pip.

The real install (a venv plus pip) is exercised by scripts/smoke-installed.sh;
here: dry runs change nothing, and the uninstaller removes exactly what its
manifest records, keeps what changed, and refuses to go near the game data.
"""
# SPDX-License-Identifier: MIT

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BASH = shutil.which("bash")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(BASH, "needs bash")
class ScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gomceix-scripts-")
        self.home = Path(self._tmp.name) / "home"
        self.prefix = self.home / ".local"
        self.data = self.prefix / "share" / "gomceix"          # the user's game
        self.data.mkdir(parents=True)
        (self.data / "world.txt").write_text("keep me")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("XDG_", "GOMCEIX_"))}
        self.env["HOME"] = str(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, name, *args):
        return subprocess.run([BASH, str(SCRIPTS / name), *args], env=self.env,
                              text=True, capture_output=True, timeout=120)

    def snapshot(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))

    def fake_install(self, edited=()):
        """A manifest as install-user.sh writes it, with real files behind it."""
        app = self.prefix / "share" / "gomceix-app"
        files = {
            self.prefix / "bin" / "gomceix": "#!/bin/sh\n",
            self.prefix / "share/applications/x.desktop": "[Desktop Entry]\n",
            self.prefix / "share/icons/hicolor/scalable/apps/x.svg": "<svg/>",
        }
        lines = []
        for directory in (app, app / "venv", self.prefix / "bin",
                          self.prefix / "share/applications",
                          self.prefix / "share/icons",
                          self.prefix / "share/icons/hicolor",
                          self.prefix / "share/icons/hicolor/scalable",
                          self.prefix / "share/icons/hicolor/scalable/apps"):
            directory.mkdir(parents=True, exist_ok=True)
        (app / "venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        for directory in (app, self.prefix / "bin",
                          self.prefix / "share/applications",
                          self.prefix / "share/icons",
                          self.prefix / "share/icons/hicolor",
                          self.prefix / "share/icons/hicolor/scalable",
                          self.prefix / "share/icons/hicolor/scalable/apps"):
            lines.append(f"dir\t-\t{directory}")
        lines.append(f"venv\t-\t{app / 'venv'}")
        for path, text in files.items():
            path.write_text(text)
            lines.append(f"file\t{sha(path)}\t{path}")
            if path in edited:
                path.write_text(text + "# edited by the user\n")
        (app / "install-manifest.txt").write_text("\n".join(lines) + "\n")
        return app, files

    def test_all_scripts_parse(self):
        for script in SCRIPTS.glob("*.sh"):
            result = subprocess.run([BASH, "-n", str(script)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, f"{script.name}: {result.stderr}")

    def test_install_dry_run_changes_nothing(self):
        before = self.snapshot()
        result = self.run_script("install-user.sh", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] create virtual environment", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_install_takes_a_prefix_and_dry_run_creates_no_directory(self):
        target = Path(self._tmp.name) / "elsewhere"
        result = self.run_script("install-user.sh", "--dry-run",
                                 "--prefix", str(target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target.exists())
        self.assertIn(str(target / "bin" / "gomceix"), result.stdout)

    def test_install_prints_an_uninstall_command_that_finds_a_custom_prefix(self):
        target = Path(self._tmp.name) / "elsewhere"
        custom = self.run_script("install-user.sh", "--dry-run",
                                 "--prefix", str(target)).stdout
        self.assertIn(f"--prefix '{target}'", custom.split("uninstall:")[1])
        default = self.run_script("install-user.sh", "--dry-run").stdout
        self.assertNotIn("--prefix", default.split("uninstall:")[1])

    def fake_venv(self, version, pip_works=True):
        """A venv as left by an earlier install, under the default prefix."""
        venv = self.prefix / "share" / "gomceix-app" / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text(f"home = /usr/bin\nversion = {version}\n")
        python = venv / "bin" / "python"
        python.write_text(f"#!/bin/sh\nexit {0 if pip_works else 1}\n")
        python.chmod(0o755)

    def dry_run_venv_line(self):
        import sys
        result = self.run_script("install-user.sh", "--dry-run",
                                 "--python", sys.executable)
        self.assertEqual(result.returncode, 0, result.stderr)
        return next(line for line in result.stdout.splitlines()
                    if "virtual environment" in line)

    def test_a_venv_from_the_same_python_is_reused(self):
        import sys
        self.fake_venv("%d.%d.1" % sys.version_info[:2])
        self.assertIn("reuse virtual environment", self.dry_run_venv_line())

    def test_a_venv_left_by_an_older_python_is_recreated(self):
        # bin/python is a symlink to the system interpreter, so it still runs
        # after an upgrade; only the recorded version gives the old venv away.
        self.fake_venv("3.1.1")
        self.assertIn("recreate", self.dry_run_venv_line())

    def test_a_venv_whose_pip_does_not_run_is_recreated(self):
        import sys
        self.fake_venv("%d.%d.1" % sys.version_info[:2], pip_works=False)
        self.assertIn("recreate", self.dry_run_venv_line())

    def test_install_rejects_unknown_options(self):
        result = self.run_script("install-user.sh", "--bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown option", result.stderr)

    def test_install_refuses_a_foreign_launcher_before_changing_anything(self):
        (self.prefix / "bin").mkdir()
        (self.prefix / "bin" / "gomceix").write_text("echo mine\n")
        before = self.snapshot()
        result = self.run_script("install-user.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not installed by this script", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_without_a_manifest_does_nothing(self):
        before = self.snapshot()
        result = self.run_script("uninstall-user.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Nothing to uninstall", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_dry_run_changes_nothing(self):
        self.fake_install()
        before = self.snapshot()
        result = self.run_script("uninstall-user.sh", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_removes_what_it_installed_and_nothing_else(self):
        self.fake_install()
        other = self.prefix / "bin" / "someone-elses-tool"
        other.write_text("x")
        result = self.run_script("uninstall-user.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.prefix / "bin" / "gomceix").exists())
        self.assertFalse((self.prefix / "share" / "gomceix-app").exists())
        self.assertFalse((self.prefix / "share" / "icons").exists())
        self.assertTrue(other.exists(), "a file it did not create was removed")
        self.assertTrue((self.prefix / "bin").is_dir(), "bin still holds a file")
        self.assertEqual((self.data / "world.txt").read_text(), "keep me")

    def test_uninstall_keeps_a_file_that_was_edited(self):
        launcher = self.prefix / "bin" / "gomceix"
        self.fake_install(edited=(launcher,))
        result = self.run_script("uninstall-user.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(launcher.exists())
        self.assertIn("changed since installation", result.stdout)

    def test_uninstall_refuses_a_manifest_entry_inside_the_game_data(self):
        app, files = self.fake_install()
        victim = self.data / "world.txt"
        with open(app / "install-manifest.txt", "a") as manifest:
            manifest.write(f"file\t{sha(victim)}\t{victim}\n")
        result = self.run_script("uninstall-user.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inside your Gomceix data", result.stderr)
        self.assertTrue(victim.exists())
        # Validated before anything was removed.
        self.assertTrue(all(path.exists() for path in files))

    def test_uninstall_refuses_entries_outside_the_prefix(self):
        app, _ = self.fake_install()
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("x")
        with open(app / "install-manifest.txt", "a") as manifest:
            manifest.write(f"file\t{sha(outside)}\t{outside}\n")
        result = self.run_script("uninstall-user.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(outside.exists())

    def test_the_game_data_path_is_protected_even_with_gomceix_home(self):
        custom = Path(self._tmp.name) / "games-elsewhere"
        custom.mkdir()
        (custom / "save").write_text("x")
        self.env["GOMCEIX_HOME"] = str(custom)
        app, _ = self.fake_install()
        # A manifest cannot be steered at it either (it is outside the prefix
        # here, so this also exercises the prefix check).
        with open(app / "install-manifest.txt", "a") as manifest:
            manifest.write(f"file\t{sha(custom / 'save')}\t{custom / 'save'}\n")
        result = self.run_script("uninstall-user.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((custom / "save").exists())

    def test_the_helper_check_accepts_the_committed_programs(self):
        result = self.run_script("build-helpers.sh", "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("unshare"), "needs unshare")
    def test_install_refuses_to_run_as_root(self):
        probe = subprocess.run(["unshare", "-r", "true"], capture_output=True)
        if probe.returncode:
            self.skipTest("user namespaces unavailable")
        result = subprocess.run(
            ["unshare", "-r", BASH, str(SCRIPTS / "install-user.sh"), "--dry-run"],
            env=self.env, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to run as root", result.stderr)


if __name__ == "__main__":
    unittest.main()
