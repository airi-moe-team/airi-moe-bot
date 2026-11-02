"""Flujo de invitación a cita antes de proponer escenas."""

import asyncio
from types import SimpleNamespace

import pytest

from airi.discord_bot.commands import dates
from airi.discord_bot import turn
from airi.domain.date_invitation import DateInvitationDecision
from airi.testing import FakeUser, make_state


class FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeChannel:
    def __init__(self):
        self.sent = []

    def typing(self):
        return FakeTyping()

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeMessage:
    def __init__(self, user):
        self.author = user
        self.channel = FakeChannel()
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append((text, kwargs))


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, text, **kwargs):
        self.sent.append((text, kwargs))


class FakeInteraction:
    def __init__(self, user):
        self.user = user
        self.channel = FakeChannel()
        self.followup = FakeFollowup()


@pytest.mark.parametrize("points", [0, 100])
@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_invitation_decision_is_independent_of_affinity(points, decision):
    async def run():
        user = FakeUser(1, "Ana")
        state, _ = make_state(
            affinity={"1": {"points": points, "last_date": 0}},
            users={"1": {"name": "Ana"}},
        )
        message = FakeMessage(user)
        calls = []

        async def evaluate(_session, _user):
            calls.append("evaluate")
            return DateInvitationDecision(decision, f"respuesta {decision}")

        async def propose(_session, _user):
            calls.append("scenes")
            return ["un paseo"]

        ctx = SimpleNamespace(
            state=state,
            busy_date_owner=lambda **_kwargs: (None, None),
            notify_busy=None,
            request_timeout=2,
            evaluate_date_invitation=evaluate,
            propose_scenes=propose,
            handle_scene_choice=None,
        )

        await dates.handle(ctx, message)
        return state, message, calls

    state, message, calls = asyncio.run(run())

    assert calls[0] == "evaluate"
    if decision == "accept":
        assert calls == ["evaluate", "scenes"]
        assert len(message.channel.sent) == 1
        assert message.channel.sent[0][1]["content"] == "respuesta accept"
        assert message.replies == []
    else:
        assert calls == ["evaluate"]
        assert message.channel.sent == []
        assert message.replies == [("respuesta reject", {"mention_author": False})]
    assert state.dates == {}
    assert state.affinity_entry(1).get("last_date", 0) == 0
    assert state.entry_points(1) == points


def test_invitation_evaluation_failure_does_not_propose_scenes_or_mutate_state():
    async def run():
        user = FakeUser(1, "Ana")
        state, _ = make_state(affinity={"1": {"points": 0}})
        message = FakeMessage(user)
        calls = []

        async def evaluate(_session, _user):
            calls.append("evaluate")
            return None

        async def propose(_session, _user):
            calls.append("scenes")
            return ["un paseo"]

        ctx = SimpleNamespace(
            state=state,
            busy_date_owner=lambda **_kwargs: (None, None),
            notify_busy=None,
            request_timeout=2,
            evaluate_date_invitation=evaluate,
            propose_scenes=propose,
            handle_scene_choice=None,
        )
        await dates.handle(ctx, message)
        return state, message, calls

    state, message, calls = asyncio.run(run())

    assert calls == ["evaluate"]
    assert message.channel.sent == []
    assert message.replies
    assert "ahora" in message.replies[0][0].lower()
    assert state.dates == {}
    assert state.affinity_entry(1).get("last_date", 0) == 0


def test_low_affinity_can_start_date_after_scene_selection(monkeypatch):
    async def run():
        user = FakeUser(1, "Ana")
        state, counters = make_state(
            affinity={"1": {"points": 0, "last_date": 0}},
            users={"1": {"name": "Ana"}},
        )
        interaction = FakeInteraction(user)

        await turn.handle_scene_choice(
            SimpleNamespace(
                state=state,
                busy_date_owner=lambda **_kwargs: (None, None),
            ),
            interaction,
            "un paseo",
        )
        return state, counters, interaction

    state, counters, interaction = asyncio.run(run())

    assert "1" in state.dates
    assert state.dates["1"]["scene"] == "un paseo"
    assert state.affinity_entry(1)["last_date"] > 0
    assert counters["dates"] == 1
    assert interaction.channel.sent
    assert interaction.followup.sent == []


def test_scene_selection_revalidates_relationship_lock():
    async def run():
        user = FakeUser(2, "Bea")
        state, _ = make_state(
            affinity={"2": {"points": 0}},
            users={"2": {"name": "Bea"}},
            world={"winner_id": "1"},
        )
        interaction = FakeInteraction(user)

        await turn.handle_scene_choice(
            SimpleNamespace(
                state=state,
                busy_date_owner=lambda **_kwargs: (None, None),
            ),
            interaction,
            "un paseo",
        )
        return state, interaction

    state, interaction = asyncio.run(run())

    assert state.dates == {}
    assert "novio" in interaction.followup.sent[0][0]
