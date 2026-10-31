"""What the Requirements page says about each component (the facts come from the core)."""
from gomceix.i18n import N_

TEXT = {
    "engine": (N_("Game engine"), N_("WineGDK, the Wine build that runs Minecraft.")),
    "xodus": (N_("Store download tool"), N_("Downloads the game from your Microsoft Store account.")),
    "webview": (N_("Store sign-in window"), N_("A web view for the Microsoft sign-in, for systems that have none.")),
    "xcurl": (N_("Online login helper"), N_("Network libraries that let the game sign in online.")),
    "umu": (N_("umu launcher"), N_("Starts the game inside a clean runtime.")),
    "java": (N_("Java runtime"), N_("Used only by ProxyPass mode.")),
    "proxypass": (N_("ProxyPass"), N_("The local proxy used in ProxyPass mode.")),
    "login-deps": (N_("Python login libraries"), N_("The cryptography package, installed for your user account only.")),
    "cache": (N_("Download cache"), N_("Archives kept after installing. Safe to delete; they are fetched again if needed.")),
}
