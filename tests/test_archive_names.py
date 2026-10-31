"""Names baked into the prebuilt upstream archives must stay exactly as built.

Renaming the project once changed three of them and every engine download was
then rejected after 860 MB ("component mismatch ... manifest has '3.0.1-bol-dgc'").
The archives are hash-pinned, so our code has to use their names, not ours.
"""
from gomceix.core import sources, vkd3d, webview


def test_the_engine_manifest_names_are_the_ones_the_archive_carries():
    assert vkd3d.VKD3D_COMPAT_COMPONENT_VERSION == "3.0.1-bol-dgc"
    assert vkd3d.REQUIRED_WINEGDK_SOURCE_MANIFEST_PATH == (
        "files/share/bedrock-on-linux/licenses-and-provenance/winegdk/native5/SOURCE-SHA256SUMS")
    paths = vkd3d._variant_relative_paths("ext-dgc")
    assert "files/lib/wine/vkd3d-proton/x86_64-windows/d3d12.dll.bol-ext-dgc" in paths
    assert all(p.endswith(".bol-ext-dgc") for p in paths)


def test_the_webkit_runtime_placeholders_are_the_ones_baked_into_its_files():
    assert webview._PLACEHOLDER == "@BOL_WEBVIEW@"
    assert webview._REWRITTEN.search(b"\x00/home/u/.local/share/x/bol-webkit-1000\x00")
    assert not webview._REWRITTEN.search(b"\x00/home/u/gomceix-webkit\x00")
    assert str(webview.webkit_dir_name() if hasattr(webview, "webkit_dir_name") else sources.WEBKIT_DIRNAME) == "bol-webkit"


def test_only_the_isolated_sources_module_spells_those_names():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "gomceix"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "sources.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("bedrock-on-linux", "BedrockOnLinux", "Wyze3306", "@BOL_", "-bol-", ".bol-", "bol-webkit"):
            if needle in text:
                offenders.append(f"{path.relative_to(root)}: {needle}")
    assert not offenders, offenders
