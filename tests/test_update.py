"""What the launcher tells a Flatpak user to run for an update.

A bundle has to be installed with the same flag as the copy it replaces.
Without --user, flatpak installs a second, system-wide copy beside the
per-user one the README sets up, and every launch keeps starting the
per-user one, still at the old version (#315).
"""
# SPDX-License-Identifier: MIT

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gomceix import i18n
from gomceix.core import update

_APP = "io.github.mdevlopm.Gomceix"

_RELEASE = {
    "version": "2.2.9",
    "url": "https://github.com/mdevlopm/gomceix/releases/tag/v2.2.9",
    "assets": [
        {"name": "gomceix_2.2.9_amd64.deb",
         "browser_download_url": "https://example.invalid/deb"},
        {"name": "Gomceix-2.2.9-x86_64.flatpak",
         "browser_download_url": "https://example.invalid/flatpak"},
    ],
}


def _flatpak_info(root, app_path):
    """A sandbox's /.flatpak-info, as flatpak run writes it."""
    path = Path(root) / "flatpak-info"
    path.write_text(
        "[Application]\n"
        "name=%s\n"
        "runtime=runtime/org.gnome.Platform/x86_64/49\n"
        "\n"
        "[Instance]\n"
        "instance-id=655197581\n"
        "instance-path=/home/player/.var/app/%s\n"
        "app-path=%s\n"
        "branch=master\n"
        "arch=x86_64\n" % (_APP, _APP, app_path))
    return path


class FlatpakInstallationTests(unittest.TestCase):
    def _installation(self, app_path):
        with tempfile.TemporaryDirectory() as td:
            return update.flatpak_installation(_flatpak_info(td, app_path))

    def test_a_per_user_install_is_user(self):
        self.assertEqual(self._installation(
            "/home/player/.local/share/flatpak/app/%s/x86_64/master/"
            "2586/files" % _APP), "user")

    def test_a_system_wide_install_is_system(self):
        self.assertEqual(self._installation(
            "/var/lib/flatpak/app/%s/x86_64/master/2586/files" % _APP),
            "system")

    def test_a_custom_installation_is_not_guessed(self):
        self.assertIsNone(self._installation(
            "/run/media/player/games/flatpak/app/%s/x86_64/master/2586/files"
            % _APP))

    def test_outside_flatpak_there_is_no_installation(self):
        self.assertIsNone(update.flatpak_installation("/nonexistent/info"))


class FlatpakUpdateMessageTests(unittest.TestCase):
    def _message(self, installation):
        with mock.patch.object(update, "update_kind", return_value="system"), \
                mock.patch.object(update, "is_flatpak", return_value=True), \
                mock.patch.object(update, "flatpak_installation",
                                  return_value=installation):
            return update.self_update(_RELEASE)

    def test_a_per_user_install_is_told_to_keep_user(self):
        state, msg = self._message("user")
        self.assertEqual(state, "system")
        self.assertIn(
            "flatpak install --user ./Gomceix-2.2.9-x86_64.flatpak",
            msg)
        self.assertIn(_RELEASE["url"], msg)

    def test_a_system_wide_install_is_told_to_stay_system_wide(self):
        _state, msg = self._message("system")
        self.assertIn(
            "flatpak install --system ./Gomceix-2.2.9-x86_64.flatpak",
            msg)

    def test_an_unknown_installation_gets_no_flag_it_might_not_have(self):
        _state, msg = self._message(None)
        self.assertIn(
            "flatpak install ./Gomceix-2.2.9-x86_64.flatpak", msg)

    def test_a_release_without_a_bundle_names_no_file_to_install(self):
        previous = i18n.language()
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, previous)
        release = dict(_RELEASE, assets=_RELEASE["assets"][:1])
        with mock.patch.object(update, "update_kind", return_value="system"), \
                mock.patch.object(update, "is_flatpak", return_value=True), \
                mock.patch.object(update, "flatpak_installation",
                                  return_value="user"):
            _state, msg = update.self_update(release)
        self.assertIn("has no Flatpak bundle", msg)
        self.assertIn(_RELEASE["url"], msg)
        self.assertNotIn("flatpak install", msg)
        self.assertNotIn("x86_64.flatpak", msg)

    def test_a_distribution_package_is_still_sent_to_its_package_manager(self):
        with mock.patch.object(update, "update_kind", return_value="system"), \
                mock.patch.object(update, "is_flatpak", return_value=False):
            state, msg = update.self_update(_RELEASE)
        self.assertEqual(state, "system")
        self.assertIn("package manager", msg)
        self.assertNotIn("flatpak", msg)


class _Run:
    """subprocess.run for the package database: owner by command."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        code, out = self.answers.get(argv[0], (1, ""))
        return mock.Mock(returncode=code, stdout=out)


class PackageFormatTests(unittest.TestCase):
    """Which installs the launcher may update through a package manager."""

    def _format(self, answers):
        with mock.patch.object(update, "is_flatpak", return_value=False):
            return update.package_format(runner=_Run(answers))

    def test_the_release_deb_is_recognised_by_dpkg(self):
        self.assertEqual(self._format({"dpkg-query": (
            0, "gomceix: /usr/lib/gomceix/gomceix/core/__init__.py\n")
        }), "deb")

    def test_the_release_rpm_is_recognised_by_rpm(self):
        self.assertEqual(self._format({"rpm": (0, "gomceix\n")}),
                         "rpm")

    def test_a_package_built_by_someone_else_is_left_to_them(self):
        self.assertIsNone(self._format({"dpkg-query": (
            0, "python3-bedrock: /usr/lib/python3/dist-packages/gomceix/core/x.py\n")}))
        self.assertIsNone(self._format({}))

    def test_never_inside_a_flatpak(self):
        with mock.patch.object(update, "is_flatpak", return_value=True):
            self.assertIsNone(update.package_format(runner=_Run(
                {"dpkg-query": (0, "gomceix: /x\n")})))


_DEB = b"!<arch>\n a release package"
_SUMS = ("%s  gomceix_2.2.9_amd64.deb\n"
         "0000000000000000000000000000000000000000000000000000000000000000"
         "  Gomceix-2.2.9-x86_64.flatpak\n")


class PackageUpdateTests(unittest.TestCase):
    """A .deb or .rpm install updates itself through its package manager
    (#294), with the file the release's checksum list names."""

    def setUp(self):
        import hashlib
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.cache = Path(holder.name)
        self.release = dict(_RELEASE, assets=_RELEASE["assets"] + [
            {"name": "SHA256SUMS",
             "browser_download_url": "https://example.invalid/sums"}])
        self.sums = _SUMS % hashlib.sha256(_DEB).hexdigest()

    def _update(self, kind="deb", served=_DEB, installed=0, tools=None):
        tools = {"pkexec", "apt-get"} if tools is None else tools

        def fetch(url, dest, label=None, progress=None):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if url.endswith("sums"):
                dest.write_text(self.sums)
            else:
                dest.write_bytes(served)

        with mock.patch.object(update, "CACHE", self.cache), \
                mock.patch.object(update, "update_kind", return_value=kind), \
                mock.patch.object(update, "download", side_effect=fetch), \
                mock.patch.object(update.shutil, "which",
                                  side_effect=lambda name: (
                                      f"/usr/bin/{name}" if name in tools
                                      else None)), \
                mock.patch.object(update.subprocess, "run",
                                  return_value=mock.Mock(
                                      returncode=installed, stdout="",
                                      stderr="E: broken")) as run:
            result = update.self_update(self.release)
        return result, run

    def test_the_checked_package_is_installed_with_apt(self):
        (state, msg), run = self._update()
        self.assertEqual(state, "ok")
        self.assertIn("restart", msg)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["pkexec", "apt-get", "install", "-y"])
        self.assertEqual(Path(argv[4]).name, "gomceix_2.2.9_amd64.deb")
        # Installed, so not kept; and the checksum list is not kept either.
        self.assertEqual(list((self.cache / "updates").iterdir()), [])

    def test_a_package_that_does_not_match_its_checksum_is_not_installed(self):
        (state, msg), run = self._update(served=b"something else")
        self.assertEqual(state, "error")
        self.assertIn("checksum", msg)
        run.assert_not_called()
        self.assertEqual(list((self.cache / "updates").iterdir()), [])

    def test_a_cancelled_password_prompt_says_how_to_install_it_by_hand(self):
        (state, msg), _ = self._update(installed=126)
        self.assertEqual(state, "error")
        self.assertIn("cancelled", msg)
        self.assertIn("sudo apt install", msg)
        self.assertTrue((self.cache / "updates" /
                         "gomceix_2.2.9_amd64.deb").is_file())

    def test_a_package_manager_failure_is_reported_with_its_words(self):
        (state, msg), _ = self._update(installed=100)
        self.assertEqual(state, "error")
        self.assertIn("E: broken", msg)

    def test_without_pkexec_the_downloaded_package_is_pointed_at(self):
        (state, msg), run = self._update(tools={"apt-get"})
        self.assertEqual(state, "system")
        self.assertIn("sudo apt install", msg)
        run.assert_not_called()

    def test_a_release_without_the_package_sends_to_the_page(self):
        self.release["assets"] = [a for a in self.release["assets"]
                                  if not a["name"].endswith(".deb")]
        (state, msg), _ = self._update()
        self.assertEqual(state, "error")
        self.assertIn(self.release["url"], msg)

    def test_an_rpm_goes_to_dnf(self):
        self.release["assets"].append(
            {"name": "gomceix-2.2.9-1.x86_64.rpm",
             "browser_download_url": "https://example.invalid/rpm"})
        self.sums += "%s  gomceix-2.2.9-1.x86_64.rpm\n" % (
            __import__("hashlib").sha256(_DEB).hexdigest())
        (state, _msg), run = self._update(kind="rpm",
                                          tools={"pkexec", "dnf"})
        self.assertEqual(state, "ok")
        self.assertEqual(run.call_args.args[0][:4],
                         ["pkexec", "dnf", "install", "-y"])


class PyzUpdateTests(unittest.TestCase):
    """A portable .pyz is held to the same checksum list as everything else."""

    def _update(self, assets):
        release = {"version": "9.9.9", "url": "https://example.invalid/v9.9.9",
                   "assets": assets}
        downloads = []

        def fetch(url, dest, label=None, progress=None):
            downloads.append(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("0" * 64 + "  gomceix-9.9.9.whl\n")

        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        target = Path(holder.name) / "gomceix.pyz"
        target.write_bytes(b"old launcher")
        with mock.patch.object(update, "CACHE", Path(holder.name) / "cache"), \
                mock.patch.object(update, "update_kind", return_value="file"), \
                mock.patch.object(update, "_self_path", return_value=target), \
                mock.patch.object(update, "download", side_effect=fetch):
            return update.self_update(release), downloads, target

    def test_a_release_without_a_checksum_list_is_refused(self):
        (state, msg), downloads, target = self._update([
            {"name": "gomceix-9.9.9.pyz",
             "browser_download_url": "https://example.invalid/pyz"}])
        self.assertEqual(state, "error")
        self.assertIn("no checksum list", msg)
        self.assertEqual(downloads, [])
        self.assertEqual(target.read_bytes(), b"old launcher")

    def test_the_checksum_list_name_the_release_workflow_writes_is_found(self):
        # release.yml writes `sha256sum gomceix-* > SHA256SUMS`.
        (state, msg), downloads, _ = self._update([
            {"name": "gomceix-9.9.9.pyz",
             "browser_download_url": "https://example.invalid/pyz"},
            {"name": "SHA256SUMS",
             "browser_download_url": "https://example.invalid/sums"}])
        self.assertEqual(state, "error")
        self.assertIn("lists no checksum", msg)
        self.assertEqual(downloads, ["https://example.invalid/sums"])


class AppImageUpdateTests(unittest.TestCase):
    """The AppImage replaces itself only with the bytes the release lists."""

    def setUp(self):
        import hashlib
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)
        self.app = self.dir / "Gomceix-2.2.8-x86_64.AppImage"
        self.app.write_bytes(b"old launcher")
        self.new = b"\x7fELF new launcher"
        self.release = {
            "version": "2.2.9", "url": "https://example.invalid/v2.2.9",
            "assets": [
                {"name": "Gomceix-2.2.9-x86_64.AppImage",
                 "browser_download_url": "https://example.invalid/app"},
                {"name": "SHA256SUMS",
                 "browser_download_url": "https://example.invalid/sums"}]}
        self.sums = "%s  Gomceix-2.2.9-x86_64.AppImage\n" % (
            hashlib.sha256(self.new).hexdigest())

    def _update(self, served):
        seen = []

        def fetch(url, dest, label=None, progress=None):
            seen.append(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if url.endswith("sums"):
                dest.write_text(self.sums)
            else:
                dest.write_bytes(served)

        with mock.patch.object(update, "CACHE", self.dir / "cache"), \
                mock.patch.object(update, "update_kind",
                                  return_value="appimage"), \
                mock.patch.dict(update.os.environ,
                                {"APPIMAGE": str(self.app)}), \
                mock.patch.object(update, "download", side_effect=fetch):
            return update.self_update(self.release), seen

    def test_a_release_with_no_checksum_list_installs_nothing(self):
        self.release["assets"] = self.release["assets"][:1]
        (state, msg), seen = self._update(self.new)
        self.assertEqual(state, "error")
        self.assertIn("no checksum list", msg)
        self.assertEqual(self.app.read_bytes(), b"old launcher")
        self.assertEqual(seen, [])

    def test_the_listed_appimage_replaces_the_running_one(self):
        (state, _msg), seen = self._update(self.new)
        self.assertEqual(state, "ok")
        self.assertEqual(self.app.read_bytes(), self.new)
        # Downloaded under a name only this release uses.
        self.assertIn("2.2.9", seen[-1].name)

    def test_bytes_the_release_does_not_list_change_nothing(self):
        (state, msg), _seen = self._update(b"half of one, half of another")
        self.assertEqual(state, "error")
        self.assertIn("checksum", msg)
        self.assertEqual(self.app.read_bytes(), b"old launcher")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()
                                if p.name != "cache"), [self.app.name])

    def test_a_partial_download_of_another_release_is_never_resumed(self):
        old_part = self.dir / f".{self.app.name}.2.2.85.new.part"
        legacy = self.dir / f"{self.app.name}.new.part"
        for leftover in (old_part, legacy):
            leftover.write_bytes(b"older release")
        self._update(self.new)
        self.assertFalse(old_part.exists())
        self.assertFalse(legacy.exists())


if __name__ == "__main__":
    unittest.main()
