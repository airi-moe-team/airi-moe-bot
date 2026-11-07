from datetime import datetime, timezone
from zoneinfo import ZoneInfoNotFoundError

import pytest

from airi.coordinator.policy import ParticipationPolicy


def timestamp(hour, minute=0):
    return datetime(2026, 11, 7, hour, minute, tzinfo=timezone.utc).timestamp()


def test_defaults_and_lima_boundaries():
    policy = ParticipationPolicy.from_env({})
    assert policy.idle_seconds == 1800
    assert policy.cooldown_seconds == 10800
    assert policy.max_interventions == 6
    assert not policy.allows_start(timestamp(13, 59))  # Lima 08:59
    assert policy.allows_start(timestamp(14))
    assert policy.allows_start(timestamp(3))  # previous local day, 22:00
    assert not policy.allows_start(timestamp(4))  # Lima 23:00
    assert policy.local_date(timestamp(4, 59)) == "2026-11-06"
    assert policy.local_date(timestamp(5)) == "2026-11-07"


def test_overnight_window():
    policy = ParticipationPolicy(start_hour=23, end_hour=9)
    assert policy.allows_start(timestamp(4))
    assert policy.allows_start(timestamp(13))
    assert not policy.allows_start(timestamp(14))
    assert not policy.allows_start(timestamp(3))


def test_new_delay_has_precedence_over_legacy_alias():
    assert ParticipationPolicy.from_env({"COORDINATOR_REPLY_DELAY": "4"}).turn_delay_seconds == 4
    assert (
        ParticipationPolicy.from_env(
            {
                "COORDINATOR_REPLY_DELAY": "4",
                "COORDINATOR_BOT_TURN_DELAY_SECONDS": "9",
            }
        ).turn_delay_seconds
        == 9
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("COORDINATOR_PROACTIVE_ENABLED", "perhaps"),
        ("COORDINATOR_IDLE_SECONDS", "0"),
        ("COORDINATOR_IDLE_SECONDS", "nan"),
        ("COORDINATOR_PROACTIVE_COOLDOWN_SECONDS", "inf"),
        ("COORDINATOR_PROACTIVE_RECHECK_SECONDS", "-1"),
        ("COORDINATOR_MAX_BOT_INTERVENTIONS", "0"),
        ("COORDINATOR_PROACTIVE_MAX_PER_DAY", "3.5"),
        ("COORDINATOR_PROACTIVE_START_HOUR", "24"),
        ("COORDINATOR_PROACTIVE_END_HOUR", "-1"),
        ("COORDINATOR_TIMEZONE", "Not/AZone"),
    ],
)
def test_invalid_configuration_fails_at_startup(name, value):
    with pytest.raises((ValueError, ZoneInfoNotFoundError)):
        ParticipationPolicy.from_env({name: value})


def test_equal_window_hours_are_rejected():
    with pytest.raises(ValueError):
        ParticipationPolicy(start_hour=9, end_hour=9)
