"""The launcher's one entry point.

``python3 -m gomceix``, the ``gomceix`` script, the zipapp (.pyz) and
the console script a wheel installs all run :func:`main`. ``optiscaler`` is
not a subcommand of :mod:`gomceix.cli`, and the OptiScaler bootstrap has to run
before it: an entry point that called ``gomceix.cli.main`` itself answered
``gomceix optiscaler install`` with "invalid choice" (#306).
"""
# SPDX-License-Identifier: MIT
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "optiscaler":
        from .optiscaler import cli_main
        entry = lambda: cli_main(sys.argv[2:])
    else:
        from .optiscaler import bootstrap
        bootstrap()
        from .cli import main as entry
    try:
        entry()
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
