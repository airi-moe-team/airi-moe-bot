from datetime import datetime, timezone

from airi.domain.prompts import diary_prompt_section, temporal_context_section
from airi.domain.time_perception import TimeConfig, build_temporal_context


def _context(*, now, users=None, history=(), in_date=False):
    return build_temporal_context(
        now,
        TimeConfig(timezone="Europe/Madrid"),
        users=users or {},
        history=history,
        user_id="7",
        in_date=in_date,
    )


def test_full_temporal_section_has_exact_moment_and_natural_context():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(
        now=now,
        users={"7": {"name": "KOKODA", "last_seen": now - 90000}},
        history=[{"role": "user", "ts": now - 2 * 3600}],
    )
    section = temporal_context_section(ctx)
    assert "martes, 27 de octubre de 2026" in section
    assert "03:14" in section
    assert "madrugada" in section
    assert "KOKODA" in section and "ayer" in section
    assert "hace 2 h" in section
    assert "no recites la hora" in section


def test_compact_section_is_one_line_with_user_gap_only():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(now=now, users={"7": {"name": "A", "last_seen": now - 120}})
    section = temporal_context_section(ctx, compact=True)
    assert "\n" not in section.strip()
    assert "madrugada" in section and "hace 2 min" in section
    assert "canal" not in section


def test_proactive_section_has_no_person_gap_and_accounts_for_daypart():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(now=now, history=[{"role": "assistant", "ts": now - 3600}])
    section = temporal_context_section(ctx, mode="proactive")
    assert "madrugada" in section
    assert "no propongas planes" in section
    assert "persona" not in section


def test_gap_lines_do_not_duplicate_or_misplace_hace():
    now = datetime(2026, 10, 27, 22, 30, tzinfo=timezone.utc).timestamp()
    ctx = _context(
        now=now,
        users={"7": {"name": "KOKODA", "last_seen": now - 3 * 3600}},
        history=[{"role": "user", "ts": now - 3 * 3600}],
    )
    section = temporal_context_section(ctx)
    assert "hace hace" not in section
    assert "Última charla con KOKODA: hace 3 h." in section
    assert "Canal inactivo: hace 3 h." in section

    yesterday = _context(
        now=now,
        users={"7": {"name": "KOKODA", "last_seen": now - 90000}},
        history=[{"role": "user", "ts": now - 90000}],
    )
    section = temporal_context_section(yesterday)
    assert "Última charla con KOKODA: ayer." in section
    assert "hace ayer" not in section


def test_habitual_schedule_is_described_without_repeating_the_clock():
    now = datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc).timestamp()
    ctx = _context(
        now=now,
        users={
            "7": {
                "name": "A",
                "last_seen": now - 3600,
                "activity_ts": [now - 4 * 86400 - 5 * 3600,
                                now - 3 * 86400 - 5 * 3600,
                                now - 2 * 86400 - 5 * 3600,
                                now - 86400 - 5 * 3600],
            }
        },
        history=[],
    )
    section = temporal_context_section(ctx)
    assert "Suele aparecer sobre las" in section
    assert "más tarde de lo habitual" in section


def test_previous_session_line_anchors_the_previous_conversation():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(
        now=now,
        users={
            "7": {
                "name": "KOKODA",
                "last_seen": now - 480,
                "activity_ts": [now - 5 * 3600, now - 480],
            }
        },
        history=[],
    )
    section = temporal_context_section(ctx)
    assert "Sesión anterior con KOKODA: ayer a las 22:14." in section
    assert "hoy" in section and "ayer" in section


def test_compact_section_mentions_previous_session_day():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(
        now=now,
        users={
            "7": {
                "name": "A",
                "last_seen": now - 480,
                "activity_ts": [now - 5 * 3600, now - 480],
            }
        },
        history=[],
    )
    section = temporal_context_section(ctx, compact=True)
    assert "sesión anterior: ayer" in section


def test_diary_entries_get_relative_time_prefix():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    txt = diary_prompt_section(
        [{"user_id": "7", "ts": now - 3 * 86400, "text": "Conocí a KOKODA."}],
        "7",
        now,
        zone=timezone.utc,
    )
    assert "- hace 3 días: Conocí a KOKODA." in txt


def test_date_section_omits_channel_gap_and_none_is_empty():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(now=now, history=[{"role": "user", "ts": now - 3600}], in_date=True)
    assert "canal" not in temporal_context_section(ctx)
    assert temporal_context_section(None) == ""
