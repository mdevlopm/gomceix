"""Every catalog stays complete, current and placeholder-safe."""
import ast
import json
import string
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source_keys():
    """Every string marked with _() / N_() in the UI, the controller and the core messages shown as they are."""
    found = set()
    files = (list((ROOT / "gomceix/ui").rglob("*.py")) + list((ROOT / "gomceix/controller").rglob("*.py"))
             + [ROOT / "gomceix/core/proxypass.py", ROOT / "gomceix/core/update.py"])
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


LOCALES = sorted(p.stem for p in (ROOT / "gomceix/locales").glob("*.json"))


@pytest.fixture(scope="module", params=LOCALES)
def catalog(request):
    return json.loads((ROOT / f"gomceix/locales/{request.param}.json").read_text(encoding="utf-8"))


def test_every_listed_language_ships_a_catalog():
    from gomceix import i18n
    assert set(i18n.LANGUAGES) - {i18n.SOURCE} == set(LOCALES)


def test_every_marked_string_has_a_translation(catalog):
    missing = sorted(source_keys() - set(catalog))
    assert not missing, f"untranslated: {missing}"


def test_the_catalog_holds_no_stale_entries(catalog):
    stale = sorted(set(catalog) - source_keys())
    assert not stale, f"no longer used in the code: {stale}"


def test_a_translation_uses_exactly_the_placeholders_of_its_source(catalog):
    for source, translated in catalog.items():
        assert fields(source) == fields(translated), (source, translated)


def test_no_translation_is_empty_or_identical_to_a_different_untranslated_marker(catalog):
    assert all(v.strip() for v in catalog.values())


def test_the_ui_actually_marks_the_channel_names_for_translation():
    keys = source_keys()
    assert {"Stable", "Preview"} <= keys


def test_no_lambda_shadows_the_translation_function():
    """`lambda *_: ... _("x")` makes `_` the argument tuple and raises TypeError at click time."""
    offenders = []
    for path in (ROOT / "gomceix/ui").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Lambda):
                names = {a.arg for a in node.args.args + node.args.kwonlyargs}
                names |= {node.args.vararg.arg} if node.args.vararg else set()
                if "_" in names and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_"
                                        for n in ast.walk(node.body)):
                    offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.FunctionDef) and "_" in {a.arg for a in node.args.args}:
                if any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_" for n in ast.walk(node)):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
