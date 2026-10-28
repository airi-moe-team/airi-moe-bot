import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from airi.domain.time_perception import (
    TimeConfig,
    build_temporal_context,
    calendar_gap_days,
    day_part,
    elapsed_text,
    format_elapsed,
    local_moment,
    resolve_zone,
)


def test_day_part_boundaries():
    assert [day_part(h) for h in (0, 5, 6, 11, 12, 19, 20, 23)] == [
        "madrugada", "madrugada", "mañana", "mañana",
        "tarde", "tarde", "noche", "noche",
    ]


def test_local_moment_uses_spanish_calendar_names():
    epoch = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    madrid, _, _ = resolve_zone("Europe/Madrid")
    moment = local_moment(epoch, madrid)
    assert moment.weekday == "martes"
    assert moment.month_name == "octubre"
    assert moment.bucket == "madrugada"


def test_resolve_zone_uses_system_when_empty_and_iana_when_given():
    system_zone, system_label, system_source = resolve_zone("")
    madrid, label, source = resolve_zone("Europe/Madrid")
    assert system_zone is None
    assert system_label == "hora local del sistema"
    assert system_source == "system"
    assert madrid is not None and label == "Europe/Madrid" and source == "override"


def test_resolve_zone_invalid_falls_back_to_system():
    zone, label, source = resolve_zone("Not/AZone")
    assert zone is None
    assert label == "hora local del sistema"
    assert source == "system"


def test_elapsed_text_clamps_negative_and_formats_units():
    assert elapsed_text(-10) == "ahora mismo"
    assert elapsed_text(59) == "ahora mismo"
    assert elapsed_text(60) == "hace 1 min"
    assert elapsed_text(3600) == "hace 1 h"
    assert elapsed_text(3 * 86400) == "hace 3 días"
    assert elapsed_text(30, short=True) == "ahora"


def test_calendar_gap_days_uses_local_dates_across_dst():
    madrid, _, _ = resolve_zone("Europe/Madrid")
    before = datetime(2026, 3, 28, 12, tzinfo=madrid).timestamp()
    after = datetime(2026, 3, 29, 12, tzinfo=madrid).timestamp()
    assert after - before == 23 * 3600
    assert calendar_gap_days(after, before, madrid) == 1
    assert format_elapsed(after, before, madrid) == "ayer"


def test_system_timezone_applies_dst_and_calendar_gap():
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        before = datetime(2026, 3, 28, 12, tzinfo=resolve_zone("Europe/Madrid")[0]).timestamp()
        after = datetime(2026, 3, 29, 12, tzinfo=resolve_zone("Europe/Madrid")[0]).timestamp()
        assert after - before == 23 * 3600
        assert calendar_gap_days(after, before, None) == 1
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def test_format_elapsed_uses_natural_day_not_24_hours():
    madrid, _, _ = resolve_zone("Europe/Madrid")
    previous = datetime(2026, 10, 26, 23, 30, tzinfo=madrid).timestamp()
    now = datetime(2026, 10, 27, 22, 30, tzinfo=madrid).timestamp()
    assert now - previous < 24 * 3600
    assert format_elapsed(now, previous, madrid) == "ayer"


def test_format_elapsed_same_long_dst_day_uses_hours_not_zero_days():
    madrid, _, _ = resolve_zone("Europe/Madrid")
    previous = datetime(2026, 10, 25, 0, 0, tzinfo=madrid, fold=0).timestamp()
    now = datetime(2026, 10, 25, 23, 30, tzinfo=madrid).timestamp()
    assert now - previous > 24 * 3600
    assert format_elapsed(now, previous, madrid) == "hace 24 h"


def test_build_temporal_context_uses_latest_history_and_snapshot_activity():
    config = TimeConfig(enabled=True)
    now = 10_000.0
    ctx = build_temporal_context(
        now,
        config,
        users={"7": {"last_seen": now - 120}},
        history=[{"role": "user", "author_id": "7", "ts": now - 900}],
        snapshot=[SimpleNamespace(author_id="8", ts=now - 30)],
        user_id=7,
        in_date=False,
    )
    assert ctx is not None
    assert ctx.user_gap_seconds == 120
    assert ctx.channel_gap_seconds == 30
    assert ctx.first_time is False


def test_build_temporal_context_first_time_and_disabled():
    args = dict(users={}, history=[], snapshot=(), user_id=7, in_date=False)
    ctx = build_temporal_context(100, TimeConfig(), **args)
    assert ctx is not None and ctx.first_time
    assert ctx.user_gap_seconds is None
    assert build_temporal_context(100, TimeConfig(enabled=False), **args) is None


def test_date_context_has_no_channel_gap():
    ctx = build_temporal_context(
        100,
        TimeConfig(),
        users={"7": {"last_seen": 90}},
        history=[{"role": "user", "ts": 80}],
        snapshot=(),
        user_id=7,
        in_date=True,
    )
    assert ctx is not None and ctx.channel_gap_seconds is None
