"""Pure helpers for text that must fit a narrow window (no GTK, so they are unit-testable)."""
from __future__ import annotations

# (longest label that keeps this size, CSS class). The big banner number is 60pt, which
# fits "26.52" in a 360 px window but not a preview build such as "26.100.123.7-preview".
_VERSION_SIZES = ((6, ""), (9, "gx-version-md"), (14, "gx-version-sm"))
_VERSION_FALLBACK = "gx-version-xs"


def version_size_class(text: str) -> str:
    """Extra CSS class that scales the banner version down as the label gets longer ('' = full size)."""
    length = len(text or "")
    for longest, css in _VERSION_SIZES:
        if length <= longest:
            return css
    return _VERSION_FALLBACK


VERSION_SIZE_CLASSES = tuple(css for _n, css in _VERSION_SIZES if css) + (_VERSION_FALLBACK,)
