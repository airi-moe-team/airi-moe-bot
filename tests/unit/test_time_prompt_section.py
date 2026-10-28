from datetime import datetime, timezone

from airi.domain.prompts import temporal_context_section
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


def test_date_section_omits_channel_gap_and_none_is_empty():
    now = datetime(2026, 10, 27, 2, 14, tzinfo=timezone.utc).timestamp()
    ctx = _context(now=now, history=[{"role": "user", "ts": now - 3600}], in_date=True)
    assert "canal" not in temporal_context_section(ctx)
    assert temporal_context_section(None) == ""
