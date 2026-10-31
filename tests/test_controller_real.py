"""LauncherController: state flow, errors and version selection, with a fake backend."""
import threading
import time

import pytest

from gomceix.core.log import BolError
from gomceix.controller.real import (IDLE, PREPARING, RUNNING, STOPPING,
                                     LauncherController, relative_day, window_action)


class NotSignedIn(Exception):
    pass


class FakeBackend:
    NotSignedIn = NotSignedIn

    def __init__(self):
        self.settings = {}
        self.editions = [{"id": "release", "beta": False}, {"id": "preview", "beta": True}]
        self.versions = {"release": [{"version": "1.21.50.4", "installed": True},
                                     {"version": "1.21.40.3", "installed": False}],
                         "preview": [{"version": "1.21.60.20", "installed": False}]}
        self.builds = []
        self.store, self.msa, self.tag = True, False, None
        self.setup_error = None
        self.launch_error = None
        self.notices = ["Your options were restored."]
        self.release_launch = threading.Event()
        self.hold_launch = False
        self.rc = 0
        self.gpus = []
        self.remove_error = None
        self.worlds = []
        self.calls = []

    def load_settings(self):
        return dict(self.settings)

    proxy_in = False
    proxy_online = True
    proxy_online_error = None
    proxy_versions = ["1.21.50", "1.21.40"]
    dest = ("127.0.0.1", "19132")

    def proxy_presets(self):
        return [("hive", "Hive", "geo.hivebedrock.network", "19132")]

    def proxy_supported(self):
        return self.proxy_versions

    def proxy_problem(self, tag, versions):
        key = ".".join(tag.split(".")[:3])
        return None if key in versions else f"ProxyPass has no build for Minecraft {key}."
    comps = {"engine": True, "java": False, "login-deps": True}
    comp_error = None

    def component_ids(self):
        return tuple(self.comps)

    def component_info(self, cid):
        return self.comps[cid], ("proxypass" if cid == "java" else "all"), cid == "login-deps"

    def component_size(self, cid):
        return 1000 if cid == "cache" else (5000 if self.comps.get(cid) else 0)

    def component_install(self, cid, progress):
        progress(1, 2)
        if self.comp_error:
            raise self.comp_error
        self.comps[cid] = True

    def component_remove(self, cid):
        self.calls.append(("remove", cid))
        self.comps[cid] = False

    def proxy_signed_in(self):
        return self.proxy_in

    def proxy_online_mode(self):
        return self.proxy_online

    def set_proxy_online_mode(self, enabled):
        if self.proxy_online_error:
            raise OSError(self.proxy_online_error)
        self.proxy_online = enabled

    def proxy_destination(self):
        return self.dest

    def set_proxy_destination(self, host, port):
        if host == "bad host":
            raise ValueError("not a valid server address")
        self.dest = (host, port)

    def proxy_logout(self):
        self.proxy_in = False

    def save_setting(self, key, value):
        self.settings[key] = value

    def list_editions(self):
        return self.editions

    def list_versions(self, edition_id, ignore_cache=False):
        if edition_id == "broken":
            raise OSError("offline")
        return self.versions[edition_id]

    def installed_builds(self, with_size=False):
        return self.builds

    def do_setup(self, edition, tag, progress, stage=None):
        self.calls.append(("setup", edition["id"], tag))
        progress(10, 100)
        if stage:
            stage("game")
        if self.setup_error:
            raise self.setup_error

    def launch(self, on_started, notices):
        self.calls.append(("launch",))
        if self.launch_error:
            raise self.launch_error
        on_started()
        notices.extend(self.notices)
        if self.hold_launch:
            assert self.release_launch.wait(5)
        return self.rc

    def exit_problem(self, rc):
        return None if rc in (None, 0) else f"Minecraft exited with code {rc}."

    def list_worlds(self):
        return self.worlds

    def list_gpus(self):
        return self.gpus

    def remove_build(self, path):
        self.calls.append(("remove", path))
        if self.remove_error:
            raise self.remove_error

    def single_window_session(self):
        return False

    def kill_wine(self):
        self.calls.append(("kill",))
        self.release_launch.set()

    def display_version(self, tag, beta):
        return ("Preview " if beta else "") + ".".join(tag.split(".")[:3])

    def store_signed_in(self):
        return self.store

    def msa_signed_in(self):
        return self.msa

    def msa_gamertag(self):
        return "Steve" if self.msa else None


def make(**kw):
    b = FakeBackend()
    for k, v in kw.items():
        setattr(b, k, v)
    c = LauncherController(b)
    c.refresh_catalog()
    events = []
    c.connect(lambda name, payload: events.append((name, payload)))
    return b, c, events


def wait_idle(c, timeout=5):
    done = threading.Event()

    def check(name, payload):
        if name == "play-state" and payload["state"] == IDLE:
            done.set()

    c.connect(check)
    if c.state == IDLE:
        return
    assert done.wait(timeout), f"stuck in {c.state}"


def names(events):
    return [n for n, _ in events]


def test_window_action_prefers_close_then_step_aside():
    assert window_action({"close_on_launch": True}, True) == "close"
    assert window_action({}, True) == "step-aside"
    assert window_action({}, False) == "stay"


def test_catalog_lists_the_current_channel_and_survives_a_dead_catalogue():
    b, c, _ = make()
    assert c.versions() == ["1.21.50", "1.21.40"]
    b.editions.append({"id": "broken", "beta": False})
    c.refresh_catalog()
    assert c.versions() == ["1.21.50", "1.21.40"]       # the broken edition cost only itself
    c.set_channel("Preview")
    assert c.channel() == "Preview" and c.versions() == ["Preview 1.21.60"]


def test_the_exact_tag_is_saved_never_the_label():
    b, c, _ = make()
    c.set_version("1.21.40")
    assert b.settings["mc_version"] == "1.21.40.3"
    assert c.selected_version() == "1.21.40"


@pytest.mark.parametrize("saved,expected", [
    ("", "1.21.50"), ("1.21.40.3", "1.21.40"), ("1.21.40", "1.21.40"),   # label shape of older releases
    ("9.9.9.9", "1.21.50")])
def test_selection_falls_back_to_newest_only_when_nothing_matches(saved, expected):
    b, c, _ = make()
    b.settings["mc_version"] = saved
    assert c.selected_version() == expected


def test_a_full_session_reports_every_state_in_order():
    b, c, events = make()
    c.play()
    wait_idle(c)
    states = [p["state"] for n, p in events if n == "play-state"]
    assert states == [PREPARING, RUNNING, IDLE]
    assert ("setup", "release", "1.21.50.4") in b.calls and ("launch",) in b.calls
    assert ("progress", {"done": 10, "total": 100}) in events
    assert ("game-started", {"window_action": "stay"}) in events
    assert "game-closed" in names(events)
    assert ("notice", {"text": "Your options were restored."}) in events
    assert "error" not in names(events)


def test_a_second_play_while_busy_is_refused_politely():
    b, c, _ = make(hold_launch=True)
    c.play()
    deadline = threading.Event()
    while c.state != RUNNING:
        deadline.wait(0.01)
    said = []
    c.play(said.append)
    assert said and "already" in said[0]
    assert [x for x in b.calls if x[0] == "setup"] == [("setup", "release", "1.21.50.4")]
    c.stop()
    wait_idle(c)


def test_stop_kills_the_game_and_ends_idle():
    b, c, events = make(hold_launch=True)
    c.play()
    while c.state != RUNNING:
        threading.Event().wait(0.01)
    c.stop()
    wait_idle(c)
    assert ("kill",) in b.calls
    assert STOPPING in [p["state"] for n, p in events if n == "play-state"]


def test_stop_is_ignored_when_nothing_runs():
    b, c, _ = make()
    c.stop()
    assert ("kill",) not in b.calls and c.state == IDLE


def test_missing_store_account_is_an_offer_not_an_error():
    b, c, events = make(setup_error=NotSignedIn("Sign in to the Store"))
    c.play()
    wait_idle(c)
    assert ("needs-store-signin", {"message": "Sign in to the Store"}) in events
    assert "error" not in names(events)


def test_other_failures_become_one_error_event_and_the_state_recovers():
    b, c, events = make(launch_error=RuntimeError("boom"))
    c.play()
    wait_idle(c)
    errors = [p for n, p in events if n == "error"]
    assert errors == [{"title": "Minecraft could not start", "message": "boom"}]
    assert c.state == IDLE


def test_an_error_without_text_still_names_its_type():
    b, c, events = make(setup_error=KeyError())
    c.play()
    wait_idle(c)
    assert [p["message"] for n, p in events if n == "error"] == ["KeyError"]


def test_play_with_no_catalogue_says_so_instead_of_starting():
    b = FakeBackend()
    c = LauncherController(b)          # catalogue never loaded
    said = []
    c.play(said.append)
    assert said and "No version" in said[0] and c.state == IDLE


def test_a_broken_listener_cannot_break_a_session():
    b, c, events = make()
    c.connect(lambda *_: (_ for _ in ()).throw(RuntimeError("listener bug")))
    c.play()
    wait_idle(c)
    assert "game-closed" in names(events)


def test_accounts_reflect_both_sign_ins_and_the_gamertag():
    b, c, _ = make(store=False, msa=True)
    ms, store = c.accounts()
    assert (ms.kind, ms.signed_in, ms.name) == ("microsoft", True, "Steve")
    assert (store.kind, store.signed_in) == ("store", False)
    assert c.account_name() == "Steve"


def test_builds_and_diagnostics_are_honest_about_missing_things():
    b, c, _ = make()
    assert c.builds() == []
    d = {x.title: x for x in c.diagnostics()}
    assert d["Game files"].status == "warn" and "Press Play" in d["Game files"].detail
    assert d["Microsoft account"].status == "warn" and d["Store account"].status == "ok"
    b.builds = [{"version": "1.21.50.4", "size": 3 * 1024 * 1024 * 1024, "in_use": True,
                 "edition": "release", "path": "/games/release/1.21.50.4"}]
    (build,) = c.builds()
    # the core's `in_use` is "PLAY would start this" = our `selected`; nothing is running
    assert (build.size_mb, build.selected, build.in_use) == (3072, True, False)
    assert (build.path, build.tag, build.channel) == ("/games/release/1.21.50.4", "1.21.50.4", "Stable")
    assert {x.title: x for x in c.diagnostics()}["Game files"].status == "ok"


# ---------------------------------------------------------------- sign-in flows
class LoginCancelled(Exception):
    pass


class FakeAuth:
    def __init__(self, link=True):
        self.link, self.stopped = link, False

    def start(self, on_auth=None, on_online=None, on_error=None):
        on_auth("https://www.microsoft.com/link", "ABCD1234")
        if self.link:
            on_online()

    def stop(self):
        self.stopped = True


def accounts_backend(**kw):
    b = FakeBackend()
    b.LoginCancelled = LoginCancelled
    b.store_calls = []
    b.store_error = None

    def store_login():
        b.store_calls.append("login")
        if b.store_error:
            raise b.store_error
    b.store_login = store_login
    b.store_logout = lambda: b.store_calls.append("logout")
    b.store_cancel = lambda: b.store_calls.append("cancel")
    b.auth = FakeAuth()
    b.msa_auth = lambda: b.auth
    b.msa_logout = lambda: b.store_calls.append("msa-logout")
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def settle(c, event_name, events, timeout=5):
    done = threading.Event()
    c.connect(lambda n, p: done.set() if n == event_name else None)
    deadline = threading.Event()
    for _ in range(int(timeout * 100)):
        if any(n == event_name for n, _ in events):
            return
        deadline.wait(0.01)
    assert done.is_set() or any(n == event_name for n, _ in events), f"no {event_name}"


def test_store_sign_in_reports_running_then_done_and_refreshes_accounts():
    b = accounts_backend()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_store()
    settle(c, "accounts-changed", events)
    states = [p["state"] for n, p in events if n == "store-login"]
    assert states == ["running", "done"] and b.store_calls == ["login"]
    assert "error" not in [n for n, _ in events]


def test_cancelling_the_store_window_is_not_an_error():
    b = accounts_backend()
    b.store_error = LoginCancelled("cancelled")
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_store()
    settle(c, "accounts-changed", events)
    assert [p["state"] for n, p in events if n == "store-login"] == ["running", "cancelled"]
    assert "error" not in [n for n, _ in events]


def test_a_failed_store_sign_in_becomes_one_error_and_can_be_retried():
    b = accounts_backend()
    b.store_error = RuntimeError("no webkit")
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_store()
    settle(c, "accounts-changed", events)
    assert [p for n, p in events if n == "error"] == [
        {"title": "Store sign-in failed", "message": "no webkit"}]
    b.store_error = None
    events.clear()
    c.sign_in_store()
    settle(c, "accounts-changed", events)
    assert b.store_calls == ["login", "login"]          # the busy flag was released


def test_only_one_store_window_at_a_time():
    b = accounts_backend()
    gate = threading.Event()
    b.store_login = lambda: gate.wait(5)
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_store()
    c.sign_in_store()
    gate.set()
    settle(c, "accounts-changed", events)
    assert [p["state"] for n, p in events if n == "store-login"].count("running") == 1


def test_microsoft_device_code_flow_publishes_the_code_then_completion():
    b = accounts_backend()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()
    assert ("ms-code", {"url": "https://www.microsoft.com/link", "code": "ABCD1234"}) in events
    assert ("ms-code-done", {"linked": True}) in events
    c.sign_in_microsoft()                                 # a finished flow can be started again
    assert [n for n, _ in events].count("ms-code") == 2


def test_cancelling_the_device_code_stops_the_poll_and_closes_the_dialog():
    b = accounts_backend(auth=FakeAuth(link=False))
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()
    c.cancel_microsoft_login()
    assert b.auth.stopped
    assert ("ms-code-done", {"linked": False}) in events
    c.cancel_microsoft_login()                            # idempotent
    assert [n for n, _ in events].count("ms-code-done") == 1


def test_sign_out_jobs_report_failures_instead_of_raising():
    b = accounts_backend()

    def boom():
        raise RuntimeError("prefix busy")
    b.msa_logout = boom
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_out_microsoft()
    settle(c, "accounts-changed", events)
    assert [p for n, p in events if n == "error"] == [
        {"title": "Could not sign out of Microsoft", "message": "prefix busy"}]
    c.sign_out_store()
    for _ in range(200):
        if "logout" in b.store_calls:
            break
        threading.Event().wait(0.01)
    assert "logout" in b.store_calls


def test_a_normal_exit_reports_no_problem():
    b, c, events = make(rc=0)
    c.play()
    wait_idle(c)
    assert "game-problem" not in names(events)


def test_an_abnormal_exit_is_reported_once_without_an_error_dialog():
    b, c, events = make(rc=3)
    c.play()
    wait_idle(c)
    assert [p for n, p in events if n == "game-problem"] == [
        {"message": "Minecraft exited with code 3.", "code": 3}]
    assert "error" not in names(events)


def test_a_close_the_user_asked_for_is_not_reported_as_a_crash():
    b, c, events = make(hold_launch=True, rc=137)
    c.play()
    while c.state != RUNNING:
        threading.Event().wait(0.01)
    c.stop()
    wait_idle(c)
    assert "game-problem" not in names(events)


def test_relative_day_reads_like_a_person_would_say_it():
    import datetime as dt
    noon = dt.datetime(2026, 10, 28, 12, 0).timestamp()
    day = 86400
    assert relative_day(noon - 3600, now=noon) == "Today"
    assert relative_day(noon - day, now=noon) == "Yesterday"
    assert relative_day(noon - 3 * day, now=noon) == "3 days ago"
    assert relative_day(noon - 35 * day, now=noon) == "Last month"
    assert relative_day(noon - 90 * day, now=noon) == "2026-07-30"
    assert relative_day(0, now=noon) == "Never played"
    # calendar days, not 24-hour blocks: 23:59 yesterday seen at 00:01 is "Yesterday"
    late = dt.datetime(2026, 10, 27, 23, 59).timestamp()
    assert relative_day(late, now=dt.datetime(2026, 10, 28, 0, 1).timestamp()) == "Yesterday"


def test_saves_maps_worlds_and_survives_a_listing_failure():
    b, c, _ = make()
    b.worlds = [{"name": "My World", "edition": "release", "modified": 0, "size": None},
                {"name": "Test & <b>", "edition": "preview", "modified": 0, "size": 5 * 1024 * 1024}]
    mine, test = c.saves()
    assert (mine.name, mine.size_mb, mine.edition, mine.last_played) == ("My World", None, "", "Never played")
    assert (test.name, test.size_mb, test.edition) == ("Test & <b>", 5, "Preview")

    def boom():
        raise OSError("disk gone")
    b.list_worlds = boom
    assert c.saves() == []


def test_a_selected_build_is_in_use_only_while_the_game_runs():
    b, c, _ = make(hold_launch=True)
    b.builds = [{"version": "1.21.50.4", "in_use": True, "edition": "release", "path": "/g/a"},
                {"version": "1.21.40.3", "in_use": False, "edition": "release", "path": "/g/b"}]
    c.play()
    while c.state != RUNNING:
        threading.Event().wait(0.01)
    running = {x.tag: x for x in c.builds()}
    assert running["1.21.50.4"].in_use and not running["1.21.40.3"].in_use
    c.stop()
    wait_idle(c)
    assert not any(x.in_use for x in c.builds())


def test_use_build_saves_the_exact_tag_and_the_channel():
    b, c, events = make()
    c.use_build("1.21.60.20", "Preview")
    assert b.settings == {"show_betas": True, "mc_version": "1.21.60.20"}
    assert "catalog-changed" in names(events) and "builds-changed" in names(events)
    assert c.selected_version() == "Preview 1.21.60"


def test_remove_build_reports_success_and_failure_and_refreshes():
    b, c, events = make()
    c.remove_build("/g/old")
    settle(c, "builds-changed", events)
    assert ("remove", "/g/old") in b.calls and "error" not in names(events)
    events.clear()
    b.remove_error = RuntimeError("Minecraft is running.")
    c.remove_build("/g/old")
    settle(c, "builds-changed", events)
    assert [p for n, p in events if n == "error"] == [
        {"title": "Could not remove the version", "message": "Minecraft is running."}]


# ------------------------------------------------------------------- settings
def test_the_settings_schema_is_well_formed():
    from gomceix.controller.settings import build_groups
    groups = build_groups()
    items = [i for g in groups for i in g.items]
    keys = [i.key for i in items]
    assert len(keys) == len(set(keys)), "a setting key appears twice"
    assert {i.kind for i in items} <= {"switch", "choice", "text", "multiline"}
    for item in items:
        if item.kind == "switch":
            assert isinstance(item.default, bool), item.key
        if item.kind == "choice":
            assert item.default in [ch.value for ch in item.choices], item.key
        assert item.title.strip(), item.key


def test_gpu_choices_come_from_the_detected_cards_after_automatic():
    b, c, _ = make()
    b.gpus = [("0000:01:00.0", "NVIDIA RTX 4070 (0000:01:00.0)"), ("0000:00:02.0", "Intel (0000:00:02.0) — runs the display")]
    gpu = next(i for g in c.settings_groups() for i in g.items if i.key == "gpu")
    assert [ch.value for ch in gpu.choices] == ["auto", "0000:01:00.0", "0000:00:02.0"]
    assert gpu.choices[0].label == "Automatic"


def test_settings_read_the_stored_value_else_the_documented_default():
    b, c, _ = make()
    assert c.get_setting("xbl_presence") is True            # default True
    assert c.get_setting("close_on_launch") is False
    assert c.get_setting("gpu") == "auto"
    assert c.get_setting("no_such_setting") is None
    b.settings["xbl_presence"] = False
    assert c.get_setting("xbl_presence") is False           # a stored False is not "missing"


def test_set_setting_saves_exactly_that_key():
    b, c, _ = make()
    c.set_setting("custom_env", "A=1\nB=2")
    c.set_setting("ray_tracing", False)
    assert b.settings == {"custom_env": "A=1\nB=2", "ray_tracing": False}


def test_a_brand_new_user_is_welcomed_and_a_returning_one_is_not():
    b, c, _ = make(store=False)
    assert c.needs_welcome() is True                       # no account, no game
    b.store = True
    assert c.needs_welcome() is False                      # signed in
    b.store, b.builds = False, [{"version": "1.21.50.4"}]
    assert c.needs_welcome() is False                      # a game is already installed
    b.installed_builds = lambda with_size=False: (_ for _ in ()).throw(OSError("boom"))
    assert c.needs_welcome() is False                      # never block the app on a failed check


def test_install_reports_stages_and_does_not_launch():
    b, c, events = make()
    c.install()
    wait_idle(c)
    assert ("setup", "bedrock", b.calls[0][2]) == b.calls[0] or b.calls[0][0] == "setup"
    assert not any(call[0] == "launch" for call in b.calls)
    assert "setup-stage" in names(events) and "setup-done" in names(events)


def test_install_needed_follows_installed_builds():
    b, c, _ = make()
    b.builds = []
    assert c.install_needed() is True
    b.builds = [{"path": "/x", "version": "1", "tag": "t", "beta": False}]
    assert c.install_needed() is False


def test_mode_defaults_to_xodus_and_switches_when_idle():
    b, c, events = make()
    assert c.mode() == "xodus"
    c.set_mode("proxypass")
    assert c.mode() == "proxypass" and b.settings["login_mode"] == "proxypass"
    assert "mode-changed" in names(events)
    c.set_mode("nonsense")
    assert c.mode() == "proxypass"


def test_mode_cannot_change_while_the_game_is_busy():
    b, c, _ = make()
    c._state = "running"
    c.set_mode("proxypass")
    assert c.mode() == "xodus"


def test_accounts_follow_the_mode():
    b, c, _ = make()
    assert [a.kind for a in c.accounts()] == ["microsoft", "store"]
    c.set_mode("proxypass")
    assert [a.kind for a in c.accounts()] == ["proxypass", "store"]
    b.proxy_in = True
    assert c.accounts()[0].signed_in and c.account_name() == "ProxyPass"


def test_online_mode_off_needs_no_proxypass_sign_in_and_on_brings_it_back():
    b, c, events = make()
    c.set_mode("proxypass")
    assert c.get_setting("proxypass_online") is True and c.needs_proxy_login() is True
    c.set_setting("proxypass_online", False)
    assert b.proxy_online is False and c.get_setting("proxypass_online") is False
    assert c.needs_proxy_login() is False
    assert [a.kind for a in c.accounts()] == ["store"]
    assert {"setting-changed", "accounts-changed"} <= set(names(events))
    c.set_setting("proxypass_online", True)
    assert c.needs_proxy_login() is True
    assert [a.kind for a in c.accounts()] == ["proxypass", "store"]


def test_online_mode_does_not_touch_the_normal_mode_sign_in():
    b, c, _ = make()
    b.proxy_online = False
    assert [a.kind for a in c.accounts()] == ["microsoft", "store"]
    assert c.needs_proxy_login() is False


def test_online_mode_off_offers_every_version_and_on_limits_them_again():
    b, c, events = make()
    everything = c.versions()
    first = c._channel_entries()[0]["tag"]
    b.proxy_problem = lambda tag, known: None if tag == first else "no build"
    c.set_mode("proxypass")
    wait_event(events, "proxy-support-changed")
    assert len(c.versions()) < len(everything)
    c.set_setting("proxypass_online", False)
    assert c.versions() == everything and "catalog-changed" in names(events)
    c.set_setting("proxypass_online", True)
    assert len(c.versions()) < len(everything)


def test_online_mode_off_lets_a_version_without_a_build_start_without_the_proxy():
    b, c, events = make()
    b.proxy_problem = lambda tag, known: "no build"
    c.set_mode("proxypass")
    wait_event(events, "proxy-support-changed")
    assert c.proxy_problem() == "no build" and c.proxy_skipped() is False
    c.set_setting("proxypass_online", False)
    assert c.proxy_problem() is None and c.proxy_skipped() is True
    c.set_mode("xodus")
    assert c.proxy_skipped() is False


def test_online_mode_that_cannot_be_saved_is_reported_and_the_switch_goes_back():
    b, c, events = make()
    b.proxy_online_error = "disk full"
    c.set_setting("proxypass_online", False)
    assert b.proxy_online is True
    assert {"error", "setting-rejected"} <= set(names(events))
    assert "setting-changed" not in names(events)


def test_online_mode_off_starts_the_game_without_asking_for_a_sign_in():
    b, c, events = _proxy_signin_setup(java=True, proxypass=True)
    b.proxy_online = False
    c.play()
    wait_event(events, "game-closed")
    assert "ms-code" not in names(events)
    assert ("setup", "release", "1.21.50.4") in b.calls


def test_proxy_server_address_is_validated_by_the_core_and_reported():
    b, c, events = make()
    assert c.get_setting("proxypass_host") == "127.0.0.1"
    c.set_setting("proxypass_host", "play.example.net")
    assert b.dest == ("play.example.net", "19132")
    c.set_setting("proxypass_port", "25565")
    assert b.dest == ("play.example.net", "25565")
    c.set_setting("proxypass_host", "bad host")
    assert b.dest[0] == "play.example.net" and "error" in names(events)


def wait_event(events, name, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if name in names(events):
            return
        time.sleep(0.01)
    raise AssertionError(f"no {name} event: {names(events)}")


def test_requirements_lists_components_and_the_cache():
    b, c, events = make()
    c.refresh_requirement_sizes()
    wait_event(events, "requirements-sizes")
    by_id = {r.id: r for r in c.requirements()}
    assert list(by_id) == ["engine", "java", "login-deps", "cache"]
    assert by_id["engine"].installed and by_id["engine"].size_bytes == 5000
    assert by_id["java"].needed_for == "proxypass" and not by_id["java"].installed
    assert not by_id["login-deps"].removable            # shared with the system
    assert by_id["cache"].kind == "cache" and not by_id["cache"].installable and by_id["cache"].size_bytes == 1000


def test_installing_and_removing_a_requirement_reports_progress_and_refreshes():
    b, c, events = make()
    c.install_requirement("java")
    wait_event(events, "requirements-changed")
    assert b.comps["java"] is True and "component-progress" in names(events)
    events.clear()
    c.remove_requirement("java")
    wait_event(events, "requirements-changed")
    assert b.comps["java"] is False and ("remove", "java") in b.calls
    assert [p["state"] for n, p in events if n == "component"] == ["running", "done"]


def test_a_failed_download_is_reported_and_clears_the_busy_flag():
    b, c, events = make()
    b.comp_error = OSError("offline")
    c.install_requirement("java")
    wait_event(events, "requirements-changed")
    assert any(n == "error" and "offline" in p["message"] for n, p in events)
    assert next(r for r in c.requirements() if r.id == "java").busy == ""


def test_components_are_not_touched_while_the_game_is_busy():
    b, c, events = make()
    c._state = "running"
    c.remove_requirement("engine")
    assert "error" in names(events) and ("remove", "engine") not in b.calls


def test_component_jobs_run_one_at_a_time():
    b, c, events = make()
    running, peak = [0], [0]
    original = b.component_remove

    def slow(cid):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.15)
        running[0] -= 1
        original(cid)

    b.component_remove = slow
    c.remove_requirement("engine")
    c.remove_requirement("java")
    deadline = time.time() + 5
    while [n for n in names(events) if n == "requirements-changed"].__len__() < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert peak[0] == 1 and ("remove", "engine") in b.calls and ("remove", "java") in b.calls


def test_diagnostics_work_in_proxypass_mode():
    """ProxyPass mode has no Microsoft account row; the checks must not assume one (it froze the Requirements page)."""
    b, c, _ = make()
    c.set_mode("proxypass")
    checks = {r.title: r for r in c.diagnostics()}
    assert "ProxyPass account" in checks and "Microsoft account" not in checks
    b.proxy_in = True
    assert {r.title: r for r in c.diagnostics()}["ProxyPass account"].status == "ok"


def test_proxypass_mode_refuses_a_game_version_it_has_no_build_for():
    b, c, events = make()
    b.versions["release"][0]["version"] = "1.26.60.1"          # the newest, not supported
    b.settings["mc_version"] = "1.26.60.1"                     # and the one the player had chosen
    c.refresh_catalog()
    c.set_mode("proxypass")
    c.refresh_proxy_support()
    wait_event(events, "proxy-support-changed")
    assert c.proxy_supported() == ["21.50", "21.40"]
    problem = c.proxy_problem()
    assert problem and "1.26.60" in problem
    said = []
    c.play(said.append)
    assert said == [problem] and c.state == "idle" and ("setup", "release", "1.26.60.1") not in b.calls


def test_the_normal_mode_never_asks_whether_proxypass_supports_a_version():
    b, c, events = make()
    b.versions["release"][0]["version"] = "1.26.60.1"
    c.refresh_catalog()
    assert c.mode() == "xodus" and c.proxy_problem() is None


def test_proxypass_mode_lists_only_the_versions_it_can_play():
    b, c, events = make()
    b.versions["release"] = [{"version": "1.26.60.1", "installed": False},
                             {"version": "1.21.50.4", "installed": True},
                             {"version": "1.21.40.3", "installed": False}]
    c.refresh_catalog()
    assert len(c.versions()) == 3                    # Normal mode offers everything
    c.set_mode("proxypass")
    c.refresh_proxy_support()
    wait_event(events, "proxy-support-changed")
    listed = c.versions()
    assert len(listed) == 2 and not any("26.60" in v for v in listed)
    # Nothing saved: the default is the newest version that can be played, not an unplayable one.
    assert "26.60" not in c.selected_version() and c.proxy_problem() is None


def test_an_unsupported_saved_choice_stays_selected_and_is_warned_about_until_changed():
    b, c, events = make()
    b.versions["release"] = [{"version": "1.26.60.1", "installed": False},
                             {"version": "1.21.50.4", "installed": True}]
    b.settings["mc_version"] = "1.26.60.1"
    c.refresh_catalog()
    c.set_mode("proxypass")
    c.refresh_proxy_support()
    wait_event(events, "proxy-support-changed")
    assert c.selected_version() not in c.versions()          # shown by the page as a placeholder
    assert c.proxy_problem() and "1.26.60" in c.proxy_problem()
    c.set_version(c.versions()[0])
    assert c.proxy_problem() is None


def _proxy_signin_setup(**comps):
    b, c, events = make()
    b.comps = {"java": False, "proxypass": False, **comps}
    b.proxy_auth = lambda: FakeAuth()
    c.set_mode("proxypass")
    events.clear()
    return b, c, events


def test_proxypass_sign_in_downloads_java_and_the_proxy_first_then_asks_for_the_login():
    b, c, events = _proxy_signin_setup()
    installed = []
    original = b.component_install
    b.component_install = lambda cid, progress: (installed.append(cid), original(cid, progress))
    c.sign_in_microsoft()
    wait_event(events, "ms-code")
    assert installed == ["java", "proxypass"]                      # in that order, before any code is shown
    order = names(events)
    assert order.index("toast") < order.index("ms-code")
    assert order.index("ms-code") > max(i for i, n in enumerate(order) if n == "component")


def test_a_failed_prerequisite_download_means_no_sign_in_is_started():
    b, c, events = _proxy_signin_setup()
    b.comp_error = OSError("offline")
    c.sign_in_microsoft()
    wait_event(events, "requirements-changed")
    time.sleep(0.2)
    assert "ms-code" not in names(events) and any(n == "error" for n in names(events))
    assert b.comps["java"] is False


def test_with_the_prerequisites_in_place_the_sign_in_starts_at_once():
    b, c, events = _proxy_signin_setup(java=True, proxypass=True)
    c.sign_in_microsoft()
    wait_event(events, "ms-code")
    assert "toast" not in names(events) and "component" not in names(events)
    assert c.proxy_missing() == []


def test_playing_in_proxypass_mode_signs_in_first_and_then_starts_the_game():
    b, c, events = _proxy_signin_setup(java=True, proxypass=True)
    b.proxy_in = False

    class LoginThatLinks:
        def start(self, on_auth=None, on_online=None, on_error=None):
            on_auth("https://www.microsoft.com/link", "ABCD1234")
            b.proxy_in = True                       # the account file now exists
            on_online()

        def stop(self):
            pass

    b.proxy_auth = lambda: LoginThatLinks()
    assert c.needs_proxy_login() is True
    c.play()
    wait_event(events, "game-closed")
    order = names(events)
    assert "toast" in order and order.index("ms-code") < order.index("setup-stage")
    assert ("setup", "release", "1.21.50.4") in b.calls and c.needs_proxy_login() is False


def test_a_signed_in_proxypass_account_goes_straight_to_the_game_and_normal_mode_never_asks():
    b, c, events = _proxy_signin_setup(java=True, proxypass=True)
    b.proxy_in = True
    c.play()
    wait_event(events, "game-closed")
    assert "ms-code" not in names(events) and "toast" not in names(events)
    b2, c2, _ = make()
    assert c2.mode() == "xodus" and c2.needs_proxy_login() is False


def test_the_server_row_offers_the_hive_and_writes_its_address():
    b, c, events = make()
    group = next(g for g in c.settings_groups() if g.title == "ProxyPass")
    item = next(i for i in group.items if i.key == "proxypass_server")
    assert [ch.value for ch in item.choices] == ["hive", "custom"] and item.choices[0].label == "Hive"
    assert c.get_setting("proxypass_server") == "custom"          # 127.0.0.1 in the fake: not a preset
    c.set_setting("proxypass_server", "hive")
    assert b.dest == ("geo.hivebedrock.network", "19132") and "proxy-destination-changed" in names(events)
    assert c.get_setting("proxypass_server") == "hive"
    events.clear()
    c.set_setting("proxypass_server", "custom")                   # choosing "custom" changes nothing
    assert b.dest == ("geo.hivebedrock.network", "19132") and names(events) == []
    c.set_setting("proxypass_host", "play.example.net")
    assert c.get_setting("proxypass_server") == "custom" and "proxy-destination-changed" in names(events)


# ------------------------------------------------------------- offline first run
def test_an_unreachable_version_list_is_told_apart_from_an_empty_one():
    b, c, events = make()
    assert not c.catalog_failed()
    b.editions = [{"id": "broken", "beta": False}]   # its fetch fails
    c.refresh_catalog()
    assert c.catalog_loaded() and c.catalog_failed() and c.versions() == []
    b.editions = [{"id": "release", "beta": False}]
    c.refresh_catalog()
    assert not c.catalog_failed() and c.versions()


def test_reloading_the_version_list_fetches_it_again_ignoring_the_cache():
    b, c, events = make()
    b.editions = [{"id": "broken", "beta": False}]
    c.refresh_catalog()
    assert c.catalog_failed() and c.versions() == []
    b.editions = [{"id": "release", "beta": False}]
    seen = []
    real = b.list_versions
    b.list_versions = lambda edition_id, ignore_cache=False: (seen.append(ignore_cache), real(edition_id))[1]
    events.clear()
    c.reload_catalog()
    assert "catalog-changed" in names(events)       # the pages say "Loading versions…" at once
    deadline = time.time() + 5
    while not c.catalog_loaded() and time.time() < deadline:
        time.sleep(0.01)
    assert c.catalog_loaded() and not c.catalog_failed() and seen == [True]
    assert c.versions()


# ------------------------------------------------------------- selected build
def test_use_build_moves_the_selected_build_before_any_play():
    b, c, _ = make()
    b.builds = [{"version": "1.21.50.4", "in_use": True, "edition": "release", "path": "/g/a"},
                {"version": "1.21.40.3", "in_use": False, "edition": "release", "path": "/g/b"}]
    assert {x.tag: x.selected for x in c.builds()} == {"1.21.50.4": True, "1.21.40.3": False}
    c.use_build("1.21.40.3", "Stable")               # the core's game folder still names the first build
    assert {x.tag: x.selected for x in c.builds()} == {"1.21.50.4": False, "1.21.40.3": True}


# ------------------------------------------------------------- unwritable data folder
def test_a_setting_that_cannot_be_saved_is_reported_and_changes_nothing():
    b, c, events = make()
    def refuse(key, value):
        raise BolError("Cannot write to /data: Read-only file system.")
    b.save_setting = refuse
    c.set_close_on_launch(True)
    c.set_setting("ray_tracing", False)
    c.set_mode("proxypass")
    c.set_channel("Preview")
    c.set_version("1.21.40")
    assert c.mode() == "xodus" and c.channel() == "Stable" and not c.close_on_launch()
    got = names(events)
    assert got.count("error") == 5 and got.count("setting-rejected") == 5
    assert "setting-changed" not in got and "mode-changed" not in got
    assert [p for n, p in events if n == "error"][0] == {
        "title": "Could not save the setting", "message": "Cannot write to /data: Read-only file system."}
