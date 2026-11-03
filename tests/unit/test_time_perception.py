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
    habitual_pattern,
    local_day_label,
    local_moment,
    previous_session,
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


def _madrid_stamp(day, hour, minute=0):
    madrid = resolve_zone("Europe/Madrid")[0]
    return datetime(2026, 10, day, hour, minute, tzinfo=madrid).timestamp()


def test_habitual_pattern_detects_a_nocturnal_schedule_across_midnight():
    madrid = resolve_zone("Europe/Madrid")[0]
    stamps = [
        _madrid_stamp(17, 22), _madrid_stamp(17, 23),
        _madrid_stamp(18, 0), _madrid_stamp(18, 1),
        _madrid_stamp(18, 23), _madrid_stamp(19, 22),
        _madrid_stamp(19, 0), _madrid_stamp(19, 23),
    ]
    now = _madrid_stamp(20, 2)
    pattern = habitual_pattern(stamps, now, madrid)
    assert pattern is not None
    assert pattern.typical_hour in (23, 0)
    assert pattern.offset_hours is not None and pattern.offset_hours > 0
    assert pattern.confidence == "alta"


def test_habitual_pattern_rejects_scattered_hours_and_few_samples():
    madrid = resolve_zone("Europe/Madrid")[0]
    now = _madrid_stamp(20, 12)
    scattered = [_madrid_stamp(day, hour) for day, hour in
                 ((17, 3), (18, 9), (19, 15), (20, 21))]
    assert habitual_pattern(scattered, now, madrid) is None
    few = [_madrid_stamp(day, 22) for day in (17, 18, 19)]
    assert habitual_pattern(few, now, madrid) is None


def test_habitual_pattern_flags_earlier_and_later_arrivals():
    madrid = resolve_zone("Europe/Madrid")[0]
    stamps = [_madrid_stamp(day, hour) for day, hour in
              ((16, 22), (17, 22), (18, 23), (19, 22))]
    early = _madrid_stamp(20, 18)
    late = _madrid_stamp(21, 3)
    assert habitual_pattern(stamps, early, madrid).offset_hours < -1.5
    assert habitual_pattern(stamps, late, madrid).offset_hours > 1.5


def test_build_temporal_context_exposes_habitual_pattern_from_activity_history():
    madrid = resolve_zone("Europe/Madrid")[0]
    now = _madrid_stamp(20, 2)
    stamps = [
        _madrid_stamp(17, 22), _madrid_stamp(18, 23),
        _madrid_stamp(19, 0), _madrid_stamp(19, 1),
        _madrid_stamp(19, 23),
    ]
    ctx = build_temporal_context(
        now,
        TimeConfig(timezone="Europe/Madrid"),
        users={
            "7": {
                "name": "A",
                "last_seen": now - 3600,
                "activity_ts": stamps,
            }
        },
        history=[],
        user_id="7",
        in_date=False,
    )
    assert ctx is not None and ctx.habitual is not None
    assert ctx.habitual.sessions == 5


def test_previous_session_skips_the_current_session_start():
    # Sesión anterior a las 05:49 y sesión actual abierta a las 20:18.
    stamps = [_madrid_stamp(19, 21), _madrid_stamp(20, 5, 49), _madrid_stamp(20, 20, 18)]
    now = _madrid_stamp(20, 20, 26)
    assert previous_session(stamps, now) == stamps[-2]


def test_previous_session_is_the_last_one_when_a_new_session_starts():
    stamps = [_madrid_stamp(19, 21), _madrid_stamp(20, 5, 49)]
    now = _madrid_stamp(20, 20, 26)
    assert now - stamps[-1] > 30 * 60
    assert previous_session(stamps, now) == stamps[-1]


def test_previous_session_is_none_without_history():
    assert previous_session([], 1000.0) is None
    assert previous_session([1000.0], 1000.0) is None


def test_build_temporal_context_exposes_previous_session_gap():
    now = _madrid_stamp(20, 20, 26)
    prev = _madrid_stamp(20, 5, 49)
    ctx = build_temporal_context(
        now,
        TimeConfig(timezone="Europe/Madrid"),
        users={"7": {"name": "A", "last_seen": now - 60, "activity_ts": [prev, now - 480]}},
        history=[],
        user_id="7",
        in_date=False,
    )
    assert ctx is not None
    assert ctx.previous_session_at == prev
    assert ctx.previous_session_gap_seconds == now - prev


def test_local_day_label_uses_calendar_days():
    madrid = resolve_zone("Europe/Madrid")[0]
    now = _madrid_stamp(20, 20, 26)
    assert local_day_label(now, _madrid_stamp(20, 5, 49), madrid) == "hoy"
    assert local_day_label(now, _madrid_stamp(19, 23, 10), madrid) == "ayer"
    assert local_day_label(now, _madrid_stamp(17, 22, 15), madrid) == "17/10"


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
