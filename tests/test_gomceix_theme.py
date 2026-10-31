"""Theme engine: validation, CSS generation, discovery (no GTK needed)."""
import json

import pytest

from gomceix.ui import theme as T


def good(**over):
    d = {"schema": 1, "id": "t1", "name": "T1", "scheme": "dark",
         "colors": {"accent": "#112233", "window": "#000"}}
    d.update(over)
    return d


def test_builtin_themes_are_valid_and_warning_free():
    themes, problems = T.discover()
    assert {"adwaita", "midnight", "forest", "paper"} <= set(themes)
    assert problems == []


def test_bad_colour_is_dropped_with_warning_not_fatal():
    t = T.parse_theme(good(colors={"accent": "red", "window": "#123456"}))
    assert "accent" not in t.colors and t.colors["window"] == "#123456"
    assert any("accent" in w for w in t.warnings)


def test_unknown_token_warns():
    t = T.parse_theme(good(colors={"accent": "#fff", "nope": "#fff"}))
    assert any("nope" in w for w in t.warnings)


@pytest.mark.parametrize("data", [
    [], "x", {"schema": 2, "id": "a"}, {"schema": 1, "id": "Bad Id"},
    {"schema": 1, "id": "ok", "scheme": "purple"},
])
def test_structurally_bad_theme_raises(data):
    with pytest.raises(T.ThemeError):
        T.parse_theme(data)


def test_shape_limits_keep_defaults():
    t = T.parse_theme(good(shape={"radius": 999, "spacing": True}))
    assert (t.radius, t.spacing) == (14, 12)
    assert len(t.warnings) == 2


def test_css_defines_adw_colours_and_readable_accent_fg():
    dark_accent = T.parse_theme(good(colors={"accent": "#101010"}))
    light_accent = T.parse_theme(good(colors={"accent": "#f0f0f0"}))
    assert "@define-color accent_fg_color #ffffff;" in T.css_for(dark_accent)
    assert "@define-color accent_fg_color #000000;" in T.css_for(light_accent)
    css = T.css_for(T.parse_theme(good(colors={"window": "#abc", "sidebar": "#def"})))
    for name in ("window_bg_color", "sidebar_bg_color", "sidebar_backdrop_color"):
        assert f"@define-color {name}" in css


def test_system_theme_defines_no_colours():
    css = T.css_for(T.Theme("adwaita", "System", "system"))
    assert "@define-color" not in css and ".gx-hero" in css


def test_load_theme_reports_broken_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(T.ThemeError):
        T.load_theme(p)


def test_user_theme_overrides_builtin_and_bad_ones_are_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = T.user_theme_dir()
    d.mkdir(parents=True)
    (d / "midnight.json").write_text(json.dumps(good(id="midnight", name="Mine")), encoding="utf-8")
    (d / "broken.json").write_text("nope", encoding="utf-8")
    themes, problems = T.discover()
    assert themes["midnight"].name == "Mine"
    assert any("broken.json" in p for p in problems)


def test_atomic_write_json_leaves_no_temp_files(tmp_path):
    target = tmp_path / "sub" / "ui.json"
    T.atomic_write_json(target, {"theme": "forest"})
    assert json.loads(target.read_text()) == {"theme": "forest"}
    assert [p.name for p in target.parent.iterdir()] == ["ui.json"]


# ----------------------------------------------------------------- backgrounds
def test_background_spec_resolves_builtins_customs_and_rejects_the_rest(tmp_path):
    for name in T.BUILTIN_BACKGROUNDS:
        spec = T.background_spec({"background": name})
        assert spec["url"].startswith("file://") and spec["url"].endswith(f"{name}.svg")
    assert T.background_spec({"background": "none"}) is None
    assert T.background_spec({}) is None
    assert T.background_spec({"background": "no-such-id"}) is None
    picture = tmp_path / "my picture.png"                      # a space: the URL must be escaped
    picture.write_bytes(b"x")
    spec = T.background_spec({"background": "custom", "background_path": str(picture)})
    assert "my%20picture.png" in spec["url"]
    assert T.background_spec({"background": "custom", "background_path": str(tmp_path / "gone.png")}) is None
    assert T.background_spec({"background": "custom", "background_path": ""}) is None


def test_the_builtin_background_files_exist_and_are_valid_svg():
    import xml.etree.ElementTree as ET
    for name in T.BUILTIN_BACKGROUNDS:
        root = ET.parse(T.BACKGROUNDS_DIR / f"{name}.svg").getroot()
        assert root.tag.endswith("svg")


@pytest.mark.parametrize("dim,expected", [(0.25, 0.25), (-1, 0.0), (5, 0.9), ("0.5", 0.5), ("x", 0.25), (None, 0.25)])
def test_the_dim_is_clamped_and_garbage_falls_back(dim, expected):
    assert T.background_spec({"background": "blocks", "background_dim": dim})["dim"] == expected


def test_css_layers_dim_then_image_then_the_accent_gradient():
    theme = T.parse_theme(good())
    css = T.css_for(theme, {"url": "file:///tmp/x.svg", "dim": 0.3})
    banner = next(line for line in css.splitlines() if line.startswith(".gx-hero { background-image"))
    assert banner.index("alpha(black, 0.3)") < banner.index('url("file:///tmp/x.svg")') < banner.index("@accent_bg_color")
    assert "cover" in banner
    assert "background-image" not in T.css_for(theme)


def test_prefs_keep_valid_background_settings_and_drop_bad_ones(tmp_path, monkeypatch):
    import json
    from gomceix.ui import prefs
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "gomceix").mkdir()
    (tmp_path / "gomceix" / "ui.json").write_text(json.dumps(
        {"background": "horizon", "background_dim": 7, "background_path": 5, "language": "tr"}), encoding="utf-8")
    loaded = prefs.load()
    assert loaded["background"] == "horizon" and loaded["language"] == "tr"
    assert loaded["background_dim"] == 0.25 and loaded["background_path"] == ""    # invalid values → defaults


def test_style_token_is_validated_and_changes_the_css():
    assert T.parse_theme(good(style="glow")).style == "glow"
    bad = T.parse_theme(good(style="neon"))
    assert bad.style == "flat" and any("style" in w for w in bad.warnings)
    assert "box-shadow" in T.css_for(T.parse_theme(good(style="glow")))
    assert "box-shadow" not in T.css_for(T.parse_theme(good(style="flat")))


def test_dark_themes_ship_and_are_clean():
    themes, problems = T.discover()
    assert {"obsidian", "aurora", "ember"} <= set(themes) and problems == []
    assert all(themes[i].scheme == "dark" for i in ("obsidian", "aurora", "ember"))


def test_setup_progress_is_monotonic_and_each_mode_sums_to_one():
    from gomceix.controller import setup_steps as setup
    for mode in ("xodus", "proxypass"):
        steps = setup.steps_for(mode)
        assert sum(s[2] for s in steps) == pytest.approx(1.0)
        seen = [setup.overall(s[0], 0, 0, mode) for s in steps]
        assert seen == sorted(seen) and seen[0] == 0.0
        assert setup.overall(steps[-1][0], 0, 0, mode) < 1.0
    assert "proxy" not in [s[0] for s in setup.steps_for("xodus")]
    assert "proxy" in [s[0] for s in setup.steps_for("proxypass")]
    assert setup.overall("game", 50, 100) == pytest.approx(0.02 + 0.35)


def test_glow_style_also_tints_popovers_and_flat_does_not():
    assert "popover.background" in T.css_for(T.parse_theme(good(style="glow")))
    assert "popover.background" not in T.css_for(T.parse_theme(good(style="flat")))
