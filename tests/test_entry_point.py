"""Every way of starting the launcher goes through gomceix.__main__.main.

``optiscaler`` is not a subcommand of gomceix.cli, and the OptiScaler bootstrap
has to run before the CLI does. The .pyz and the console script a wheel
installs called gomceix.cli.main themselves, so both answered
``gomceix optiscaler install`` with "invalid choice" (#306).
"""
# SPDX-License-Identifier: MIT

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gomceix.core import __main__ as entry
from gomceix.core import cli, optiscaler

ROOT = Path(__file__).resolve().parents[1]


class DispatchTests(unittest.TestCase):
    def test_optiscaler_goes_to_its_own_cli_without_the_bootstrap(self):
        with mock.patch.object(sys, "argv",
                               ["gomceix", "optiscaler", "status"]), \
                mock.patch.object(optiscaler, "cli_main") as cli_main, \
                mock.patch.object(optiscaler, "bootstrap") as bootstrap, \
                mock.patch.object(cli, "main") as main:
            entry.main()
        cli_main.assert_called_once_with(["status"])
        bootstrap.assert_not_called()
        main.assert_not_called()

    def test_every_other_command_runs_the_bootstrap_then_the_cli(self):
        calls = []
        with mock.patch.object(sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(optiscaler, "bootstrap",
                                  side_effect=lambda: calls.append("boot")), \
                mock.patch.object(cli, "main",
                                  side_effect=lambda: calls.append("cli")):
            entry.main()
        self.assertEqual(calls, ["boot", "cli"])

    def test_ctrl_c_exits_with_130(self):
        with mock.patch.object(sys, "argv", ["gomceix", "play"]), \
                mock.patch.object(optiscaler, "bootstrap"), \
                mock.patch.object(cli, "main", side_effect=KeyboardInterrupt), \
                mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as stop:
                entry.main()
        self.assertEqual(stop.exception.code, 130)


class EntryPointTests(unittest.TestCase):
    def test_the_script_answers_the_optiscaler_subcommand(self):
        # `python3 -m gomceix` is the entry point every installation ends up in.
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, PYTHONPATH=str(ROOT), HOME=home,
                       XDG_DATA_HOME=os.path.join(home, "data"),
                       XDG_CONFIG_HOME=os.path.join(home, "config"),
                       XDG_CACHE_HOME=os.path.join(home, "cache"))
            env.pop("GOMCEIX_HOME", None)
            result = subprocess.run(
                [sys.executable, "-m", "gomceix", "optiscaler", "--help"],
                env=env, cwd=ROOT, text=True, capture_output=True,
                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gomceix optiscaler", result.stdout)


if __name__ == "__main__":
    unittest.main()
