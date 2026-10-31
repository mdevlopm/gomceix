"""Plain data returned by the controller. No GTK, no backend imports."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    kind: str            # "microsoft" (in-game / Xbox) | "store" (game download)
    signed_in: bool
    name: str | None     # gamertag or account name when known
    detail: str = ""     # one short line shown under the name


@dataclass(frozen=True)
class SaveInfo:
    name: str
    size_mb: int | None  # None = not measured (walking a world is slow)
    last_played: str     # already formatted for display
    edition: str = ""    # "" or a label such as "Preview" worth showing


@dataclass(frozen=True)
class CheckResult:
    title: str
    status: str          # "ok" | "warn" | "error"
    detail: str = ""     # what to do next when status != ok


@dataclass(frozen=True)
class BuildInfo:
    version: str
    channel: str         # "Stable" | "Preview"
    size_mb: int | None      # None = not measured (walking a build is slow)
    selected: bool = False   # the version PLAY will start
    in_use: bool = False     # a running game uses it: it must not be removed
    path: str = ""           # folder on disk (what Remove acts on)
    tag: str = ""            # exact build id (what a selection is saved as)


@dataclass(frozen=True)
class RequirementInfo:
    id: str
    title: str
    description: str
    installed: bool
    size_bytes: int | None       # None = not measured yet
    needed_for: str = "all"      # "all" | "proxypass"
    installable: bool = True
    removable: bool = True
    busy: str = ""               # "" | "installing" | "removing"
    kind: str = "component"      # "component" | "cache"
