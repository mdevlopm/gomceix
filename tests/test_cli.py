"""Offline command-line dispatch regressions."""
# SPDX-License-Identifier: MIT

import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from gomceix.core import cli, deps
from gomceix.core.log import BolError
from gomceix.core.network import NetworkCheck


class CliTests(unittest.TestCase):
    def test_direct_launcher_error_is_printed_before_cli_exit(self):
        output = io.StringIO()
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "profiles", "create", "../bad"]), \
                mock.patch.object(
                    cli, "require_profile_shortcuts_supported"), \
                mock.patch.object(
                    cli, "create_profile",
                    side_effect=BolError("invalid profile name")), \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIn("invalid profile name", output.getvalue())

    def test_regular_setup_preserves_existing_dispatch(self):
        with mock.patch.object(
                sys, "argv", ["gomceix", "setup", "--force"]), \
                mock.patch.object(cli, "do_setup") as setup, \
                mock.patch.object(cli, "ok"):
            cli.main()

        setup.assert_called_once_with(
            mc_edition=None, mc_version=None, force=True)

    def test_play_says_when_nothing_is_signed_in_for_online_play(self):
        # The launcher window warns before starting the game (#240); a
        # terminal that just launches leaves the same absence to be found
        # in-game, as Realms and servers quietly missing.
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(cli, "msa_signed_in", return_value=False), \
                mock.patch.object(cli, "launch") as launch, \
                contextlib.redirect_stdout(output):
            cli.main()

        # A warning, not a refusal: offline is a real way to play.
        self.assertTrue(launch.called)
        printed = output.getvalue()
        self.assertIn("Not signed in for online play", printed)
        self.assertIn("login", printed)

    def test_play_says_nothing_when_the_account_is_there(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(cli, "msa_signed_in", return_value=True), \
                mock.patch.object(cli, "launch") as launch, \
                contextlib.redirect_stdout(output):
            cli.main()

        self.assertTrue(launch.called)
        self.assertNotIn("Not signed in", output.getvalue())

    def test_profile_create_prints_profile_shortcut_and_command(self):
        profile = Path("/tmp/gomceix-profiles/family")
        shortcut = Path("/tmp/applications/gomceix-family.desktop")
        output = io.StringIO()
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "profiles", "create", "Family"]), \
                mock.patch.object(
                    cli, "create_profile", return_value=profile) as create, \
                mock.patch.object(
                    cli, "write_profile_shortcut",
                    return_value=shortcut) as write_shortcut, \
                mock.patch.object(
                    cli, "profile_launch_command",
                    return_value="GOMCEIX_HOME=/tmp/family gomceix gui"
                ) as launch_command, \
                mock.patch.object(cli, "ok") as success, \
                contextlib.redirect_stdout(output):
            cli.main()

        create.assert_called_once_with("Family")
        write_shortcut.assert_called_once_with(
            "Family",
            profile_dir=profile,
        )
        launch_command.assert_called_once_with(profile)
        self.assertEqual(
            [call.args[0] for call in success.call_args_list],
            [f"Profile: {profile}", f"Desktop shortcut: {shortcut}"],
        )
        self.assertIn(
            "Steam command: GOMCEIX_HOME=/tmp/family gomceix gui",
            output.getvalue(),
        )

    def test_shortcut_creates_a_direct_launch_entry_for_the_default_install(
            self):
        shortcut = Path("/tmp/applications/gomceix-play.desktop")
        output = io.StringIO()
        with mock.patch.object(
                sys, "argv", ["gomceix", "shortcut"]), \
                mock.patch.object(cli, "require_shortcuts_supported"), \
                mock.patch.object(cli, "create_profile") as create, \
                mock.patch.object(
                    cli, "write_play_shortcut",
                    return_value=shortcut) as write_shortcut, \
                mock.patch.object(
                    cli, "play_launch_command",
                    return_value="gomceix play") as launch_command, \
                mock.patch.object(
                    cli, "direct_launch_readiness",
                    return_value=["Sign in from the launcher once."]), \
                mock.patch.object(cli, "warn") as warned, \
                mock.patch.object(cli, "info"), \
                mock.patch.object(cli, "ok") as success, \
                contextlib.redirect_stdout(output):
            cli.main()

        create.assert_not_called()
        write_shortcut.assert_called_once_with(
            profile_name=None, profile_dir=None)
        launch_command.assert_called_once_with(None)
        success.assert_called_once_with(f"Desktop shortcut: {shortcut}")
        self.assertIn("Steam command: gomceix play",
                      output.getvalue())
        warned.assert_called_once_with("Sign in from the launcher once.")

    def test_profile_shortcut_reports_no_readiness_for_another_home(self):
        profile = Path("/tmp/gomceix-profiles/family")
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "shortcut", "--profile", "Family"]), \
                mock.patch.object(cli, "require_shortcuts_supported"), \
                mock.patch.object(
                    cli, "create_profile", return_value=profile), \
                mock.patch.object(
                    cli, "write_play_shortcut", return_value=Path("/tmp/e")), \
                mock.patch.object(
                    cli, "play_launch_command", return_value="cmd"), \
                mock.patch.object(
                    cli, "direct_launch_readiness") as readiness, \
                mock.patch.object(cli, "info"), \
                mock.patch.object(cli, "ok"), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main()

        # Settings under the current GOMCEIX_HOME say nothing about the profile.
        readiness.assert_not_called()

    def test_windowless_play_failure_reaches_the_desktop(self):
        with mock.patch.object(
                sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(cli, "IS_TTY", False), \
                mock.patch.object(
                    cli, "launch",
                    side_effect=BolError("No game — choose a version")), \
                mock.patch.object(cli, "desktop_notify") as notified, \
                mock.patch.object(cli, "err"), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIn("No game — choose a version", notified.call_args.args[0])

    def test_terminal_play_failure_is_not_duplicated_as_a_notification(self):
        with mock.patch.object(
                sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(cli, "IS_TTY", True), \
                mock.patch.object(
                    cli, "launch", side_effect=BolError("prefix busy")), \
                mock.patch.object(cli, "desktop_notify") as notified, \
                mock.patch.object(cli, "err"), \
                self.assertRaises(SystemExit):
            cli.main()

        notified.assert_not_called()

    def test_profile_list_prints_all_known_profiles(self):
        output = io.StringIO()
        profiles = [
            {
                "name": "Alice",
                "slug": "alice",
                "path": "/tmp/profiles/alice",
            },
            {
                "name": "Bob",
                "slug": "bob",
                "path": "/tmp/profiles/bob",
            },
        ]
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "profiles", "list"]), \
                mock.patch.object(
                    cli, "list_profiles", return_value=profiles) as listing, \
                contextlib.redirect_stdout(output):
            cli.main()

        listing.assert_called_once_with()
        self.assertIn("Alice (alice): /tmp/profiles/alice", output.getvalue())
        self.assertIn("Bob (bob): /tmp/profiles/bob", output.getvalue())

    def test_empty_profile_list_is_reported(self):
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "profiles", "list"]), \
                mock.patch.object(cli, "list_profiles", return_value=[]), \
                mock.patch.object(cli, "info") as informational:
            cli.main()

        informational.assert_called_once_with("No isolated profiles.")

    def test_doctor_network_combines_system_and_network_results(self):
        checks = [
            NetworkCheck("dns", "xbox.example", True, "resolved"),
            NetworkCheck("tls", "xbox.example", False, "timed out"),
            NetworkCheck("clock", "host", None, "status unavailable"),
        ]
        output = io.StringIO()
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "doctor", "--network"]), \
                mock.patch.object(
                    cli, "doctor", return_value=True) as system_doctor, \
                mock.patch.object(
                    cli, "diagnose_network",
                    return_value=(False, checks)) as network_doctor, \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        system_doctor.assert_called_once_with(False)
        network_doctor.assert_called_once_with(None)
        report = output.getvalue()
        self.assertIn("dns", report)
        self.assertIn("OK", report)
        self.assertIn("ÉCHEC", report)
        self.assertIn("INFO", report)

    def test_doctor_host_implies_network_checks(self):
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "doctor", "--host", "192.0.2.7"]), \
                mock.patch.object(cli, "doctor", return_value=True), \
                mock.patch.object(
                    cli, "diagnose_network",
                    return_value=(True, [])) as network_doctor, \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 0)
        network_doctor.assert_called_once_with("192.0.2.7")

    def test_plain_doctor_does_not_run_network_checks(self):
        with mock.patch.object(
                sys, "argv", ["gomceix", "doctor"]), \
                mock.patch.object(
                    cli, "doctor", return_value=True) as system_doctor, \
                mock.patch.object(cli, "diagnose_network") as network_doctor, \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 0)
        system_doctor.assert_called_once_with(False)
        network_doctor.assert_not_called()

    def test_failed_system_doctor_is_not_masked_by_healthy_network(self):
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "doctor", "--network"]), \
                mock.patch.object(cli, "doctor", return_value=False), \
                mock.patch.object(
                    cli, "diagnose_network", return_value=(True, [])), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)


class ChromeOsWindowTests(unittest.TestCase):
    """Qt's Wayland backend crashed the window in ChromeOS's container (#302)."""

    def _root(self, tmp, marker=True):
        root = Path(tmp)
        if marker:
            (root / "dev").mkdir()
            (root / "dev" / ".cros_milestone").write_text("128\n")
        return root

    def test_the_container_gets_xwayland(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
            self.assertTrue(cli._prefer_x11_on_chromeos(env, self._root(tmp)))
        self.assertEqual(env["QT_QPA_PLATFORM"], "xcb")

    def test_the_compositor_alone_is_enough_to_tell(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DISPLAY": ":0", "SOMMELIER_VERSION": "0.20"}
            self.assertTrue(cli._prefer_x11_on_chromeos(
                env, self._root(tmp, marker=False)))
        self.assertEqual(env["QT_QPA_PLATFORM"], "xcb")

    def test_a_platform_someone_chose_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"}
            self.assertFalse(cli._prefer_x11_on_chromeos(env, self._root(tmp)))
        self.assertEqual(env["QT_QPA_PLATFORM"], "wayland")

    def test_nothing_changes_without_xwayland_or_off_chromeos(self):
        with tempfile.TemporaryDirectory() as tmp:
            no_x = {"WAYLAND_DISPLAY": "wayland-0"}
            self.assertFalse(cli._prefer_x11_on_chromeos(no_x, self._root(tmp)))
            desktop = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
            self.assertFalse(cli._prefer_x11_on_chromeos(
                desktop, self._root(tmp + "-none", marker=False)))
        self.assertNotIn("QT_QPA_PLATFORM", no_x)
        self.assertNotIn("QT_QPA_PLATFORM", desktop)


class SudoRefusalTests(unittest.TestCase):
    def test_nothing_runs_as_root_for_someone_else(self):
        # `sudo ... doctor --acknowledge-gpu-crash` looked at root's data
        # and found no incident to acknowledge (#299).
        output = io.StringIO()
        with mock.patch.object(
                sys, "argv",
                ["gomceix", "doctor", "--acknowledge-gpu-crash"]), \
                mock.patch.dict(os.environ, {"SUDO_USER": "bilal"}), \
                mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch("gomceix.core.util._ensure_xdg_storage") as storage, \
                mock.patch.object(cli, "doctor") as doctor, \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIn("without sudo", output.getvalue())
        storage.assert_not_called()
        doctor.assert_not_called()


class LauncherStartTests(unittest.TestCase):
    """Starting the launcher opens the launcher — in Game Mode too."""

    def _run(self, argv, gamescope):
        # The UI is imported where it is used, so a fake `gomceix.ui.app`
        # stands in for the window (no GTK is needed to run these tests).
        window = mock.Mock(return_value=0)
        fake_ui = types.ModuleType("gomceix.ui.app")
        fake_ui.main = window
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.dict(sys.modules, {"gomceix.ui.app": fake_ui}), \
                mock.patch.object(cli, "_gtk_missing", return_value=None), \
                mock.patch.object(cli, "launch") as launched, \
                mock.patch.object(cli, "info"), \
                mock.patch("gomceix.core.gpu_safety.in_gamescope_session",
                           return_value=gamescope):
            cli.main()
        return launched, window

    def test_the_window_opens_in_every_session(self):
        # The 2.1.4 behaviour — Game Mode starts the game and never shows the
        # launcher — also fired on the reporter's desktop session (#127, #130).
        for gamescope in (True, False):
            for argv in (["gomceix"], ["gomceix", "gui"]):
                with self.subTest(argv=argv, gamescope=gamescope):
                    launched, window = self._run(argv, gamescope)
                    window.assert_called_once_with([cli.APP])
                    launched.assert_not_called()

    def test_play_stays_the_launcher_free_path(self):
        launched, window = self._run(["gomceix", "play"], True)
        launched.assert_called_once_with(editor=False)
        window.assert_not_called()

    def test_betterrtx_commands_reach_the_manager(self):
        for argv, expected in (
                (["betterrtx", "list"], ("list", None)),
                (["betterrtx", "install", "default"], ("install", "default")),
                (["betterrtx", "restore"], ("restore", None))):
            with self.subTest(argv=argv), \
                    mock.patch.object(sys, "argv", ["gomceix"] + argv), \
                    mock.patch("gomceix.core.betterrtx.cli") as manager:
                cli.main()
            manager.assert_called_once_with(*expected)

    def test_betterrtx_install_needs_something_to_install(self):
        with mock.patch.object(sys, "argv",
                               ["gomceix", "betterrtx", "install"]), \
                mock.patch("gomceix.core.betterrtx.cli") as manager, \
                self.assertRaises(SystemExit):
            cli.main()
        manager.assert_not_called()

    def test_play_editor_opens_bedrock_editor(self):
        launched, window = self._run(
            ["gomceix", "play", "--editor"], True)
        launched.assert_called_once_with(editor=True)
        window.assert_not_called()

    def test_shortcut_launch_failure_reaches_the_desktop(self):
        # A shortcut leaves no terminal, so the notification is the only place
        # this can surface.
        with mock.patch.object(sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(cli, "IS_TTY", False), \
                mock.patch.object(
                    cli, "launch",
                    side_effect=BolError("No game — choose a version")), \
                mock.patch.object(cli, "desktop_notify") as notified, \
                mock.patch.object(cli, "err"), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIn("No game — choose a version", notified.call_args.args[0])

    def test_window_failure_is_not_reported_as_a_launch_failure(self):
        fake_ui = types.ModuleType("gomceix.ui.app")
        fake_ui.main = mock.Mock(side_effect=BolError("window failed"))
        with mock.patch.object(sys, "argv", ["gomceix", "gui"]), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.dict(sys.modules, {"gomceix.ui.app": fake_ui}), \
                mock.patch.object(cli, "_gtk_missing", return_value=None), \
                mock.patch.object(cli, "IS_TTY", False), \
                mock.patch.object(cli, "desktop_notify") as notified, \
                mock.patch.object(cli, "err"), \
                self.assertRaises(SystemExit):
            cli.main()

        notified.assert_not_called()

    def test_the_window_opens_with_a_clean_argv(self):
        # Gtk.Application treats extra argv words as files to open; the
        # subcommand (`gui`) must not reach it.
        _launched, window = self._run(["gomceix", "gui"], gamescope=False)
        window.assert_called_once_with([cli.APP])

    def test_missing_gtk_is_reported_plainly_with_what_to_install(self):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["gomceix", "gui"]), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}), \
                mock.patch.object(cli, "_gtk_missing",
                                  return_value="needs GTK 4: install python3-gi"), \
                contextlib.redirect_stdout(output), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 1)
        self.assertIn("python3-gi", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_other_commands_never_import_the_toolkit(self):
        # `doctor` and `play` must keep working on a host without GTK.
        with mock.patch.object(sys, "argv", ["gomceix", "doctor"]), \
                mock.patch.object(cli, "_gtk_missing",
                                  side_effect=AssertionError("GTK probed")), \
                mock.patch.object(cli, "doctor"), \
                self.assertRaises(SystemExit) as exited:
            cli.main()

        self.assertEqual(exited.exception.code, 0)


class UpdateCommandTests(unittest.TestCase):
    """`update` and `changelog` must not call a failed lookup a success."""

    def run_cli(self, command, lookup):
        out, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["gomceix", command]), \
                mock.patch("gomceix.core.util.refuse_sudo"), \
                mock.patch("gomceix.core.util._ensure_xdg_storage"), \
                mock.patch("gomceix.core.update.gh_latest", lookup), \
                mock.patch("gomceix.core.util.gh_latest", lookup), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(errors):
            try:
                cli.main()
            except SystemExit as exited:
                return exited.code, out.getvalue() + errors.getvalue()
        return 0, out.getvalue() + errors.getvalue()

    def test_a_failed_check_is_not_reported_as_up_to_date(self):
        code, text = self.run_cli(
            "update", mock.Mock(side_effect=OSError("HTTP Error 404")))
        self.assertEqual(code, 1)
        self.assertIn("Could not check for updates", text)
        self.assertIn("404", text)
        self.assertNotIn("up to date", text)

    def test_a_check_that_found_nothing_newer_says_up_to_date(self):
        code, text = self.run_cli("update", mock.Mock(
            return_value={"tag_name": "v0.0.1"}))
        self.assertEqual(code, 0)
        self.assertIn("up to date", text)

    def test_a_failed_changelog_fetch_exits_with_an_error(self):
        code, text = self.run_cli(
            "changelog", mock.Mock(side_effect=OSError("HTTP Error 404")))
        self.assertEqual(code, 1)
        self.assertIn("Error fetching changelog", text)


class GuiToolkitVersionTests(unittest.TestCase):
    """deps.gui_import_error against a libadwaita that imports but is too old."""

    def error_for(self, major, minor):
        gi = types.ModuleType("gi")
        gi.require_version = lambda *args: None
        repository = types.ModuleType("gi.repository")
        repository.Gtk = object()
        repository.Adw = types.SimpleNamespace(
            get_major_version=lambda: major, get_minor_version=lambda: minor)
        gi.repository = repository
        with mock.patch.dict(
                sys.modules, {"gi": gi, "gi.repository": repository}):
            return deps.gui_import_error()

    def test_a_libadwaita_older_than_the_window_needs_is_reported(self):
        message = self.error_for(1, 2)
        self.assertIn("libadwaita 1.2 is too old", message)
        self.assertIn("1.5", message)

    def test_the_minimum_and_newer_are_accepted(self):
        self.assertIsNone(self.error_for(1, 5))
        self.assertIsNone(self.error_for(1, 10))
        self.assertIsNone(self.error_for(2, 0))


class GtkProbeTests(unittest.TestCase):
    """`_gtk_missing` itself, not mocked: it once referenced a name nobody imported,
    and every test that replaced it kept that from showing."""

    def test_it_runs_and_answers_none_or_a_message(self):
        answer = cli._gtk_missing()
        self.assertTrue(answer is None or isinstance(answer, str))

    def test_a_missing_toolkit_names_the_packages_and_the_cause(self):
        with mock.patch.object(deps, "gui_import_error", return_value="No module named 'gi'"):
            message = cli._gtk_missing()
        self.assertIn("python3-gi", message)
        self.assertIn("python3-gobject", message)
        self.assertIn("No module named 'gi'", message)

    def test_a_working_toolkit_is_not_reported(self):
        with mock.patch.object(deps, "gui_import_error", return_value=None):
            self.assertIsNone(cli._gtk_missing())


if __name__ == "__main__":
    unittest.main()
