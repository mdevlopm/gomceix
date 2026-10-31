"""The public docs name the built-in themes and the theme keys the code reads."""
# SPDX-License-Identifier: MIT

from pathlib import Path

from gomceix.ui import theme

ROOT = Path(__file__).resolve().parents[1]
THEMES_DOC = (ROOT / "docs" / "themes.md").read_text(encoding="utf-8")


def test_the_theme_guide_lists_every_built_in_theme():
    built_in = sorted((ROOT / "gomceix" / "ui" / "themes").glob("*.json"))
    assert built_in, "no built-in themes found"
    missing = [p.name for p in built_in if f"`{p.name}`" not in THEMES_DOC]
    assert not missing, f"not described in docs/themes.md: {missing}"


def test_the_theme_guide_documents_every_style_the_code_reads():
    missing = [style for style in theme.STYLES if f"`{style}`" not in THEMES_DOC]
    assert not missing, f"not documented in docs/themes.md: {missing}"


def test_the_theme_guide_gives_the_shape_limits_the_code_enforces():
    for key, (lo, hi) in theme.SHAPE_LIMITS.items():
        assert f"{lo}–{hi}" in THEMES_DOC or f"{lo}-{hi}" in THEMES_DOC, key
