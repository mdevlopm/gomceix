"""Installing a game that has to be downloaded asks for the Store sign-in first, then carries on by itself."""
import time

import pytest

from gomceix.controller.real import LauncherController
from tests.test_controller_real import FakeBackend, LoginCancelled, names, wait_event, wait_idle


def signed_out_backend(installed=False):
    b = FakeBackend()
    b.LoginCancelled = LoginCancelled
    b.store = False
    b.login_calls = []
    b.cancel_login = False
    b.versions["release"] = [{"version": "1.21.50.4", "installed": installed},
                             {"version": "1.21.40.3", "installed": False}]

    def store_login():
        b.login_calls.append("login")
        if b.cancel_login:
            raise LoginCancelled()
        b.store = True                      # signing in succeeded
    b.store_login = store_login
    return b


def controller(b):
    c = LauncherController(b)
    c.refresh_catalog()
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    return c, events


@pytest.mark.parametrize("action", ["play", "install"])
def test_the_login_comes_before_the_download_and_the_download_follows_it(action):
    b = signed_out_backend()
    c, events = controller(b)
    getattr(c, action)()
    wait_event(events, "setup-done")
    order = names(events)
    assert b.login_calls == ["login"]
    assert "toast" in order and order.index("toast") < order.index("store-login") < order.index("setup-stage")
    assert ("setup", "release", "1.21.50.4") in b.calls            # the chosen version was downloaded afterwards
    wait_idle(c)


def test_a_cancelled_login_downloads_nothing_and_leaves_the_launcher_idle():
    b = signed_out_backend()
    b.cancel_login = True
    c, events = controller(b)
    c.play()
    wait_event(events, "store-login")
    time.sleep(0.3)
    assert c.state == "idle" and not any(call[0] == "setup" for call in b.calls)
    assert [p["state"] for n, p in events if n == "store-login"][-1] == "cancelled"


def test_a_game_that_is_already_installed_does_not_ask_for_a_login():
    b = signed_out_backend(installed=True)
    c, events = controller(b)
    assert c.needs_store_login() is False
    c.play()
    wait_event(events, "setup-done")
    assert b.login_calls == [] and "toast" not in names(events)


def test_an_account_that_is_signed_in_goes_straight_to_the_download():
    b = signed_out_backend()
    b.store = True
    c, events = controller(b)
    assert c.needs_store_login() is False
    c.install()
    wait_event(events, "setup-done")
    assert b.login_calls == []


def test_a_second_press_while_the_login_window_is_open_opens_no_second_window():
    b = signed_out_backend()
    import threading
    gate = threading.Event()
    original = b.store_login
    b.store_login = lambda: (gate.wait(5), original())
    c, events = controller(b)
    c.play()
    wait_event(events, "store-login")
    c.play()
    gate.set()
    wait_event(events, "setup-done")
    assert b.login_calls == ["login"]
