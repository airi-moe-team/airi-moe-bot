"""Registro de sesiones de actividad para inferir el horario habitual."""

from airi.domain.users import (
    ACTIVITY_SAMPLES_MAX,
    ACTIVITY_SESSION_GAP_SECONDS,
    register_activity,
)


def test_first_registration_seeds_activity_history():
    users = {}
    assert register_activity(users, user_id=7, display_name="A", now=1000.0) is True
    entry = users["7"]
    assert entry["activity_ts"] == [1000.0]
    assert entry["last_seen"] == 1000.0


def test_messages_within_the_same_session_do_not_add_samples():
    users = {}
    register_activity(users, user_id=7, display_name="A", now=1000.0)
    register_activity(
        users, user_id=7, display_name="A", now=1000.0 + ACTIVITY_SESSION_GAP_SECONDS - 1
    )
    assert users["7"]["activity_ts"] == [1000.0]
    assert users["7"]["last_seen"] == 1000.0 + ACTIVITY_SESSION_GAP_SECONDS - 1


def test_new_session_after_the_gap_is_recorded():
    users = {}
    register_activity(users, user_id=7, display_name="A", now=1000.0)
    register_activity(
        users, user_id=7, display_name="A", now=1000.0 + ACTIVITY_SESSION_GAP_SECONDS
    )
    assert users["7"]["activity_ts"] == [
        1000.0,
        1000.0 + ACTIVITY_SESSION_GAP_SECONDS,
    ]


def test_clock_backwards_is_ignored_for_activity_history():
    users = {"7": {"name": "A", "activity_ts": [2000.0]}}
    register_activity(users, user_id=7, display_name="A", now=1000.0)
    assert users["7"]["activity_ts"] == [2000.0]
    assert users["7"]["last_seen"] == 1000.0


def test_activity_history_is_sanitized_and_capped():
    users = {"7": {"name": "A", "activity_ts": ["basura", None, -1]}}
    for index in range(ACTIVITY_SAMPLES_MAX + 5):
        register_activity(
            users,
            user_id=7,
            display_name="A",
            now=10_000.0 + index * ACTIVITY_SESSION_GAP_SECONDS,
        )
    history = users["7"]["activity_ts"]
    assert len(history) == ACTIVITY_SAMPLES_MAX
    assert all(isinstance(value, float) for value in history)
    assert history == sorted(history)
