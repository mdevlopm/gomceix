"""Describes the launcher's settings as data, so the UI draws them generically.

Adding a setting is one `Item` here; no page code changes. Keys are the ones the
backend already reads from `settings.json`.
"""
from __future__ import annotations

from dataclasses import dataclass
from gomceix.i18n import _


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class Item:
    key: str
    kind: str                      # "switch" | "choice" | "text" | "multiline"
    title: str
    subtitle: str = ""
    default: object = None
    choices: tuple = ()            # tuple[Choice, ...] for kind == "choice"


@dataclass(frozen=True)
class Group:
    title: str
    items: tuple
    description: str = ""


AUTO_GPU = "auto"


def resolve_choice(item: Item, current) -> tuple[list, int]:
    """(choices, selected index) for a "choice" item whose stored value is `current`.

    The settings file is hand-editable, so `current` may be anything: a value
    that names something no longer there (an unplugged eGPU) is shown as such,
    and a stored null/number/list is compared as text instead of raising.
    """
    choices = list(item.choices)
    values = [choice.value for choice in choices]
    if current is None or current == "":
        current = item.default
    if isinstance(current, (list, dict)):
        current = str(current)
    for index, value in enumerate(values):
        if value == current or value == str(current):
            return choices, index
    choices.append(Choice(str(current), _("Not found ({value})", value=current)))
    return choices, len(choices) - 1


def build_groups(gpu_choices=(), proxy_presets=()):
    """All setting groups. `gpu_choices`: Choice items for the detected graphics cards."""
    return [
        Group(_("General"), (
            Item("close_on_launch", "switch", _("Close the launcher when the game starts"),
                 _("Come back by opening Gomceix again."), False),
            Item("xbl_presence", "switch", _("Show what I am playing"),
                 _("Shares the game as your Xbox (and Discord) activity."), True),
            Item("confine_cursor", "switch", _("Keep the mouse inside the game window"),
                 "", False),
        )),
        Group(_("Graphics"), (
            Item("gpu", "choice", _("Graphics card"),
                 _("On a laptop with two cards, choose the one Minecraft plays on."), AUTO_GPU,
                 (Choice(AUTO_GPU, _("Automatic")),) + tuple(gpu_choices)),
            Item("ray_tracing", "switch", _("Ray tracing materials"),
                 _("Allows RTX-style materials on cards that support them."), True),
            Item("limit_frame_rate", "switch", _("Limit the frame rate"),
                 _("Keeps the game from drawing more frames than your screen shows."), True),
            Item("renderer", "choice", _("Renderer"), _("Change only if the game will not start."), "auto",
                 (Choice("auto", _("Automatic")), Choice("opengl", _("OpenGL")))),
        )),
        Group(_("ProxyPass"), (
            Item("proxypass_server", "choice", _("Server"),
                 _("Pick a ready-made server, or type your own address below."), "custom",
                 tuple(proxy_presets) + (Choice("custom", _("Custom address")),)),
            Item("proxypass_host", "text", _("Server address"),
                 _("The server ProxyPass connects you to."), "127.0.0.1"),
            Item("proxypass_port", "text", _("Server port"),
                 _("Usually 19132."), "19132"),
            Item("proxypass_online", "switch", _("Online mode"),
                 _("Signs you in with Microsoft. Off joins only servers that do not check accounts."), True),
        ), _("Used in ProxyPass mode. In the game, open the ProxyPass world on the Worlds tab.")),
        Group(_("Advanced"), (
            Item("custom_env", "multiline", _("Extra environment variables"),
                 _("NAME=value pairs, one per line or separated by spaces; quote a value that contains spaces. Applied when the game starts."), ""),
            Item("gamescope", "text", _("Gamescope options"),
                 _("Arguments for gamescope, without the program name. Leave empty to start the game directly."), ""),
            Item("diagnostics", "switch", _("Extra startup diagnostics"),
                 _("Writes more detail to the logs. Useful for bug reports."), False),
            Item("allow_unpinned_proton", "switch", _("Accept unverified game engine downloads"),
                 _("Lets a custom engine download without a published checksum. Off keeps downloads verified."), False),
            Item("allow_unpinned_proxypass", "switch", _("Accept unverified ProxyPass downloads"),
                 _("Lets the ProxyPass file download without a published checksum. Off keeps downloads verified."), False),
        ), _("Only change these if you know why.")),
    ]
