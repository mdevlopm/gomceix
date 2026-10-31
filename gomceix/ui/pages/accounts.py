from __future__ import annotations

from gi.repository import Adw, Gtk

from .. import widgets
from .requirements import human_size
from gomceix.i18n import _, N_

TITLE, ICON = N_("Accounts"), "avatar-default-symbolic"

LABELS = {"microsoft": N_("Microsoft account (play online)"),
          "proxypass": N_("ProxyPass account (play online)"),
          "store": N_("Store account (download the game)")}


def build(win):
    c = win.controller
    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(
        title=_("Sign-ins"),
        description=((_("In ProxyPass mode the Store account downloads the game and ProxyPass signs you in to play online.")
                      if any(a.kind == "proxypass" for a in c.accounts()) else
                      _("Online mode is off in the ProxyPass settings, so only the Store account is used here."))
                     if c.mode() == "proxypass" else
                     _("Gomceix needs two sign-ins with the same Microsoft account: the Store account downloads the game, the Microsoft account lets you play online.")))
    # A rebuilt page (language change, mode switch...) must still know a Store window is open.
    store_state = {"running": bool(getattr(c, "store_login_running", lambda: False)())}

    for acct in c.accounts():
        subtitle = acct.name if acct.signed_in and acct.name else (
            _("Signed in") if acct.signed_in else acct.detail)
        r = widgets.row(_(LABELS.get(acct.kind, acct.kind)), subtitle)
        r.add_prefix(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
        running = acct.kind == "store" and not acct.signed_in and store_state["running"]
        if acct.signed_in:
            btn = widgets.button(_("Sign out"), "secondary", small=True)
            action = c.sign_out_microsoft if acct.kind in ("microsoft", "proxypass") else c.sign_out_store
        else:
            btn = widgets.button(_("Cancel") if running else _("Sign in"), "primary", small=True)
            if running:
                r.set_subtitle(_("Waiting for the sign-in window…"))
            action = c.sign_in_microsoft if acct.kind in ("microsoft", "proxypass") else c.sign_in_store

        def clicked(_b, action=action, kind=acct.kind):
            if kind == "store" and store_state["running"]:
                c.cancel_store_login()      # the same button cancels an open sign-in window
            else:
                action()

        btn.connect("clicked", clicked)
        r.add_suffix(btn)
        group.add(r)

        if acct.kind == "proxypass" and not acct.signed_in:
            def on_prereq(payload, btn=btn, row=r, detail=acct.detail):
                cid = payload.get("id")
                if cid not in ("java", "proxypass"):
                    return
                state = payload.get("state")
                if state == "running":
                    btn.set_sensitive(False)
                    row.set_subtitle(_("Getting ProxyPass ready…"))
                elif state in ("done", "refused"):
                    btn.set_sensitive(True)
                    row.set_subtitle(detail)

            def on_prereq_progress(payload, row=r):
                cid, total = payload.get("id"), payload.get("total") or 0
                if cid in ("java", "proxypass") and total > 0:
                    name = _("Java runtime") if cid == "java" else _("ProxyPass")
                    row.set_subtitle(name + "  ·  " + _("Downloading… {done} of {total}",
                                                       done=human_size(payload.get("done") or 0),
                                                       total=human_size(total)))
            win.on("component", on_prereq, owner="accounts")
            win.on("component-progress", on_prereq_progress, owner="accounts")

        if acct.kind == "store" and not acct.signed_in:
            def on_store(payload, btn=btn, row=r, detail=acct.detail):
                running = payload.get("state") == "running"
                store_state["running"] = running
                btn.set_label(_("Cancel") if running else _("Sign in"))
                row.set_subtitle(_("Waiting for the sign-in window…") if running else detail)
            win.on("store-login", on_store, owner="accounts")
    page.add(group)
    page.add(Adw.PreferencesGroup(
        description=_("Your password is never stored by Gomceix; tokens stay on this computer.")))
    return page
