from tests.support import load_addon_module

sessions = load_addon_module("core.command_session", namespace="command_session_tests")


def test_old_delivery_cannot_replace_reactivated_session():
    state = sessions.CommandSession()
    state.activate()
    old = state.begin_choices("first")
    state.dismiss()
    state.activate()
    assert not state.accepts(old, "first")
    assert not state.set_choices(old, "first", [sessions.Choice("old", "Old")])
    assert state.phase is sessions.Phase.COMMANDS


def test_provider_change_and_shutdown_fence_deliveries():
    state = sessions.CommandSession()
    state.activate()
    token = state.begin_choices("first")
    assert not state.accepts(token, "second")
    state.close()
    assert not state.accepts(token, "first")
    state.activate()
    assert state.phase is sessions.Phase.IDLE


def test_every_stable_choice_is_reachable_on_pages():
    state = sessions.CommandSession()
    state.activate()
    token = state.begin_choices("provider")
    choices = [sessions.Choice(str(index), f"Model {index}") for index in range(24)]
    assert state.set_choices(token, "provider", choices)
    reached = []
    for _ in range(3):
        reached.extend(state.choice(digit).id for digit in range(1, 10) if state.choice(digit))
        if state.choice(0):
            reached.append(state.choice(0).id)
        state.move_page(1)
    assert reached == [choice.id for choice in choices]
    state.move_page(-1)
    assert state.page == 1
