"""Gomceix — install & run Minecraft Bedrock (Windows GDK) on Linux.

GDK-Proton built from a WineGDK fork gives native in-game Microsoft login.

This is a plain package with no import-time side effects: the entry points are
:func:`gomceix.cli.main` (CLI/GUI dispatch) and :mod:`gomceix.__main__`
(``python3 -m gomceix`` and the packaged ``.pyz``).
"""
# SPDX-License-Identifier: MIT
from .config import VERSION
from . import relocation as relocation

__version__ = VERSION
