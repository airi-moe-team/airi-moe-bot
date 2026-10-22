"""Notas privadas de autodescubrimiento."""

from __future__ import annotations

from airi.domain.self_notes import add_note, normalize_notes, recent_notes


def test_add_note_deduplicates_normalized_text():
    notes = []
    first = add_note(notes, "Me gustan los días de lluvia", now=10.0)
    duplicate = add_note(notes, "me gustan los días de lluvia!", now=11.0)
    assert first is not None
    assert duplicate is None
    assert len(notes) == 1


def test_notes_are_capped():
    notes = []
    for i in range(5):
        add_note(notes, f"nota {i}", now=float(i), max_notes=3)
    assert len(notes) == 3
    assert recent_notes(notes, 2) == ["nota 3", "nota 4"]


def test_normalize_notes_ignores_invalid_entries():
    assert normalize_notes([None, {"text": ""}, {"text": "ok"}]) == [
        {"ts": 0.0, "text": "ok", "source": "reflection"}
    ]
