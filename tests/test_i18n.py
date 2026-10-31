"""The translation layer: language detection, lookup, placeholders, fallbacks."""
import json

import pytest

from gomceix import i18n


@pytest.fixture(autouse=True)
def _restore_language():
    yield
    i18n.set_language("en")


@pytest.mark.parametrize("env,expected", [
    ({}, "en"),
    ({"LANG": "tr_TR.UTF-8"}, "tr"),
    ({"LANG": "zh_CN.UTF-8"}, "zh"),
    ({"LANGUAGE": "zh_TW:en"}, "zh"),
    ({"LANGUAGE": "fr_FR:tr_TR"}, "tr"),        # an unsupported first choice must not end the search
    ({"LANGUAGE": "de:fr", "LANG": "tr_TR.UTF-8"}, "tr"),
    ({"LANG": "C.UTF-8"}, "en"),
    ({"LANG": "POSIX", "LC_ALL": "tr_TR"}, "tr"),
    ({"LC_ALL": "tr", "LANG": "en_US.UTF-8"}, "tr"),   # LC_ALL beats LANG
    ({"LANG": "tr_TR@euro"}, "tr"),
    ({"LANG": "TR-tr"}, "tr"),
    ({"LANG": "xx_YY"}, "en"),
])
def test_detect(env, expected):
    assert i18n.detect(env) == expected


def test_untranslated_text_is_returned_as_is_and_placeholders_are_filled():
    i18n.set_language("en")
    assert i18n._("Play") == "Play"
    assert i18n._("{n} backups", n=3) == "3 backups"


def test_a_catalog_translates_and_formats(monkeypatch):
    monkeypatch.setattr(i18n, "_catalog", {"Play": "Oyna", "{n} backups": "{n} yedek"})
    assert i18n._("Play") == "Oyna"
    assert i18n._("{n} backups", n=2) == "2 yedek"
    assert i18n._("Not translated yet") == "Not translated yet"


def test_a_broken_translation_never_breaks_the_screen(monkeypatch):
    monkeypatch.setattr(i18n, "_catalog", {"{n} backups": "{count} yedek", "Hi {x}": "Selam {"})
    assert i18n._("{n} backups", n=2) == "2 backups"      # wrong placeholder name → source text
    assert i18n._("Hi {x}", x="a") == "Hi a"              # malformed format string → source text


def test_set_language_system_follows_the_environment_and_unknown_falls_back():
    assert i18n.set_language("system", {"LANG": "tr_TR.UTF-8"}) == "tr"
    assert i18n.language() == "tr"
    assert i18n.set_language("klingon") == "en"
    assert i18n.set_language("en") == "en"


def test_a_missing_or_corrupt_catalog_is_just_english(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    assert i18n.load_catalog("tr") == {}
    (tmp_path / "tr.json").write_text("{not json", encoding="utf-8")
    assert i18n.load_catalog("tr") == {}
    (tmp_path / "tr.json").write_text(json.dumps({"A": "B", "C": "", "D": 5}), encoding="utf-8")
    assert i18n.load_catalog("tr") == {"A": "B"}          # empty and non-string values are ignored


def test_n_marks_without_translating(monkeypatch):
    monkeypatch.setattr(i18n, "_catalog", {"Play": "Oyna"})
    assert i18n.N_("Play") == "Play"
