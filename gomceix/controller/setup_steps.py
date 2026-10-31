"""Install stages shown on the setup screen (pure data: no GTK)."""
from gomceix.i18n import N_

# (stage id from the core, label, relative weight). Downloads dominate.
STEPS = (
    ("deps", N_("Preparing components"), 0.02),
    ("game", N_("Downloading game files"), 0.70),
    ("engine", N_("Installing the game engine"), 0.20),
    ("proxy", N_("Downloading ProxyPass and Java"), 0.10),
    ("prefix", N_("Setting up the Wine environment"), 0.06),
    ("finish", N_("Finishing touches"), 0.02),
)
PROXY_ONLY = frozenset({"proxy"})


def steps_for(mode: str = "xodus"):
    """The steps this mode installs, with weights that add up to 1."""
    steps = [s for s in STEPS if mode == "proxypass" or s[0] not in PROXY_ONLY]
    total = sum(s[2] for s in steps)
    return [(sid, label, weight / total) for sid, label, weight in steps]


def overall(stage: str, done: int, total: int, mode: str = "xodus") -> float:
    """Whole-install fraction: finished steps plus the share of the running one."""
    base = 0.0
    for sid, _label, share in steps_for(mode):
        if sid == stage:
            inner = min(done / total, 1.0) if total and stage in ("game", "engine", "proxy") else 0.0
            return base + share * inner
        base += share
    return 0.0
