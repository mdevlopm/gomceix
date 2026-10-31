"""Controller state-machine holes: jobs that interleave, sign-ins that fail or are
cancelled, and data the backend cannot read. All with the fake backend."""
import threading

from gomceix.controller.real import IDLE, RUNNING, LauncherController
from tests.test_controller_real import FakeAuth, accounts_backend, make, names, settle, wait_idle


def wait_for(predicate, timeout=5):
    gate = threading.Event()
    for _i in range(int(timeout * 200)):
        if predicate():
            return
        gate.wait(0.005)
    raise AssertionError("condition never became true")


# ------------------------------------------------- components vs. play / install
def test_a_refused_component_job_still_answers_so_a_queue_cannot_wait_forever():
    b, c, events = make(hold_launch=True)
    c.play()
    wait_for(lambda: c.state == RUNNING)
    c.install_requirement("java")                 # a game is running: refused with a message ...
    assert ("component", {"id": "java", "state": "refused"}) in events
    assert [p["title"] for n, p in events if n == "error"] == ["Download failed"]
    assert ("component", {"id": "java", "state": "running"}) not in events
    c.stop()
    wait_idle(c)


def test_asking_for_the_same_component_twice_is_answered_too():
    b, c, events = make()
    gate = threading.Event()
    original = b.component_install
    b.component_install = lambda cid, progress: (gate.wait(5), original(cid, progress))
    c.install_requirement("java")
    c.install_requirement("java")
    assert ("component", {"id": "java", "state": "refused"}) in events
    gate.set()
    wait_for(lambda: ("component", {"id": "java", "state": "done"}) in events)


def test_play_and_install_wait_for_a_running_component_job():
    b, c, events = make()
    gate = threading.Event()
    original = b.component_install
    b.component_install = lambda cid, progress: (gate.wait(5), original(cid, progress))
    c.install_requirement("java")
    said = []
    c.play(said.append)
    c.install(said.append)
    assert len(said) == 2 and all("component" in text for text in said)
    assert c.state == IDLE and not [x for x in b.calls if x[0] in ("setup", "launch")]
    gate.set()
    wait_for(lambda: ("component", {"id": "java", "state": "done"}) in events)
    c.play()                                      # and it works again once the job has ended
    wait_idle(c)
    assert ("launch",) in b.calls


# ------------------------------------------------------------- sign-in failures
def test_a_microsoft_sign_in_that_cannot_start_reports_an_error_and_can_be_retried():
    b = accounts_backend()

    class Boom:
        def start(self, **_kw):
            raise RuntimeError("no network")

        def stop(self):
            pass

    b.auth = Boom()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()
    assert [p["message"] for n, p in events if n == "error"] == ["no network"]
    assert ("ms-code-done", {"linked": False}) in events
    b.auth = FakeAuth()
    c.sign_in_microsoft()                         # the flag was released: a retry reaches the backend
    assert ("ms-code-done", {"linked": True}) in events


def test_a_backend_that_cannot_even_build_the_sign_in_is_an_error_not_an_exception():
    b = accounts_backend()
    b.msa_auth = lambda: (_ for _ in ()).throw(OSError("registry locked"))
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()                         # used to raise into the button handler
    assert [p["message"] for n, p in events if n == "error"] == ["registry locked"]
    b.msa_auth = lambda: b.auth
    c.sign_in_microsoft()
    assert [n for n, _p in events].count("ms-code") == 1


def test_a_code_that_arrives_after_cancel_does_not_reopen_the_dialog():
    b = accounts_backend()
    late = {}

    class Slow:
        def start(self, on_auth=None, on_online=None, **_kw):
            late["on_auth"], late["on_online"] = on_auth, on_online

        def stop(self):
            pass

    b.auth = Slow()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()
    c.cancel_microsoft_login()
    late["on_auth"]("https://www.microsoft.com/link", "LATE")
    late["on_online"]()                           # a poll that finished just as the user cancelled
    assert "ms-code" not in names(events)
    assert [n for n, _p in events].count("ms-code-done") == 1


def test_a_stale_finish_cannot_clear_a_newer_sign_in():
    b = accounts_backend()
    callbacks = []

    class Slow:
        def start(self, on_auth=None, on_online=None, **_kw):
            callbacks.append(on_online)

        def stop(self):
            pass

    b.auth = Slow()
    b.msa_auth = lambda: Slow()
    c = LauncherController(b)
    c.sign_in_microsoft()
    c.cancel_microsoft_login()
    c.sign_in_microsoft()                         # a second attempt is now the current one
    callbacks[0]()                                # the first one's worker finishes late
    c.sign_in_microsoft()                         # still busy: this must be ignored, not start a third
    assert len(callbacks) == 2


def test_switching_mode_cancels_a_sign_in_started_in_the_old_mode():
    b = accounts_backend(auth=None)

    class Waiting:
        stopped = False

        def start(self, **_kw):
            pass

        def stop(self):
            Waiting.stopped = True

    b.msa_auth = lambda: Waiting()
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    c.sign_in_microsoft()
    c.set_mode("proxypass")
    assert Waiting.stopped and ("ms-code-done", {"linked": False}) in events
    assert c.mode() == "proxypass"


def test_store_login_running_tells_a_rebuilt_page_to_show_cancel():
    b = accounts_backend()
    gate = threading.Event()
    b.store_login = lambda: gate.wait(5)
    c = LauncherController(b)
    events = []
    c.connect(lambda n, p: events.append((n, p)))
    assert c.store_login_running() is False
    c.sign_in_store()
    assert c.store_login_running() is True
    gate.set()
    settle(c, "accounts-changed", events)
    assert c.store_login_running() is False


# ------------------------------------------------------------ maintenance / builds
def test_repair_pressed_twice_resets_the_prefix_once():
    b, c, events = make()
    gate = threading.Event()
    resets = []
    b.reset_prefix = lambda: (resets.append(1), gate.wait(5))
    c.repair()
    wait_for(lambda: resets)
    c.repair()
    gate.set()
    wait_for(lambda: ("maintenance", {"job": "repair", "state": "done"}) in events)
    assert resets == [1]
    c.repair()                                    # and a later repair is allowed again
    wait_for(lambda: len(resets) == 2)


def test_the_selected_build_cannot_be_removed_while_the_game_starts_or_runs():
    b, c, events = make(hold_launch=True)
    b.builds = [{"version": "1.21.50.4", "in_use": True, "edition": "release", "path": "/g/a"},
                {"version": "1.21.40.3", "in_use": False, "edition": "release", "path": "/g/b"}]
    c.play()
    wait_for(lambda: c.state == RUNNING)
    c.remove_build("/g/a")
    assert ("remove", "/g/a") not in b.calls
    assert [p["title"] for n, p in events if n == "error"] == ["Could not remove the version"]
    c.remove_build("/g/b")                        # another build is not in the way
    wait_for(lambda: ("remove", "/g/b") in b.calls)
    c.stop()
    wait_idle(c)
    c.remove_build("/g/a")                        # nothing runs any more
    wait_for(lambda: ("remove", "/g/a") in b.calls)


def test_a_component_the_ui_has_no_text_for_does_not_break_the_requirements_page():
    b, c, _ = make()
    b.comps = {**b.comps, "future-thing": False}
    ids = [r.id for r in c.requirements()]
    assert "future-thing" in ids and ids[-1] == "cache"
    unknown = next(r for r in c.requirements() if r.id == "future-thing")
    assert unknown.title == "future-thing" and unknown.description == ""


def test_an_unreadable_sign_in_state_counts_as_signed_out_instead_of_breaking_the_page():
    b, c, _ = make()

    def boom():
        raise OSError("registry unreadable")
    b.msa_signed_in = boom
    b.store_signed_in = boom
    ms, store = c.accounts()
    assert not ms.signed_in and not store.signed_in
    assert {x.title: x for x in c.diagnostics()}["Store account"].status == "warn"


def test_an_unreadable_games_folder_still_gives_a_library_and_health_page():
    b, c, _ = make()

    def boom(with_size=False):
        raise PermissionError("denied")
    b.installed_builds = boom
    assert c.builds() == []
    assert {x.title: x for x in c.diagnostics()}["Game files"].status == "warn"


def test_a_finished_install_tells_the_library_there_is_a_new_build():
    b, c, events = make()
    c.install()
    wait_idle(c)
    order = names(events)
    assert order.index("setup-done") < order.index("builds-changed")


def test_changing_a_setting_announces_it_so_other_pages_can_follow():
    b, c, events = make()
    c.set_close_on_launch(True)
    c.set_setting("renderer", "opengl")
    assert ("setting-changed", {"key": "close_on_launch", "value": True}) in events
    assert ("setting-changed", {"key": "renderer", "value": "opengl"}) in events


def test_a_proxy_destination_save_does_not_announce_a_change_it_did_not_make():
    b, c, events = make()
    c.set_setting("proxypass_host", "bad host")
    assert "setting-changed" not in names(events) and "error" in names(events)



# ------------------------------------------------------------------ settings choices
def test_a_hand_edited_choice_setting_never_breaks_the_settings_page():
    from gomceix.controller.settings import AUTO_GPU, Choice, Item, build_groups, resolve_choice
    gpu = next(i for g in build_groups((Choice("0000:01:00.0", "RTX"),)) for i in g.items if i.key == "gpu")
    choices, index = resolve_choice(gpu, "0000:01:00.0")
    assert choices[index].value == "0000:01:00.0" and len(choices) == 2
    assert resolve_choice(gpu, AUTO_GPU)[1] == 0
    assert resolve_choice(gpu, None)[1] == 0 and resolve_choice(gpu, "")[1] == 0     # null: the default
    gone, index = resolve_choice(gpu, "0000:09:00.0")                                  # an unplugged card
    assert gone[index].label == "Not found (0000:09:00.0)" and len(gone) == 3
    odd, index = resolve_choice(gpu, 7)                                                # a number: used to raise ValueError
    assert odd[index].value == "7"
    listy, index = resolve_choice(gpu, ["x"])
    assert listy[index].value == "['x']"
    plain = Item("renderer", "choice", "R", default="auto", choices=(Choice("auto", "A"), Choice("opengl", "O")))
    assert resolve_choice(plain, "opengl")[1] == 1
