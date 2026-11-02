"""Notas privadas de autodescubrimiento."""

from __future__ import annotations

from airi.domain.self_notes import (
    add_note,
    normalize_notes,
    recent_notes,
    remove_legacy_diary_discoveries,
)


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


def test_generic_self_discovery_is_not_saved_or_injected():
    notes = []
    assert add_note(notes, "Me estoy descubriendo poco a poco.", now=1) is None
    assert add_note(notes, "Hipótesis: Me estoy descubriendo poco a poco.", now=2) is None
    assert normalize_notes([
        {"text": "Me estoy descubriendo poco a poco."},
        {"text": "Hipótesis: Me estoy descubriendo poco a poco."},
        {"text": "Me gusta escuchar historias."},
    ]) == [{"ts": 0.0, "text": "Me gusta escuchar historias.", "source": "reflection"}]


def test_note_with_label_is_rejected_if_content_is_generic():
    notes = []
    assert add_note(notes, "Hipótesis: Me estoy descubriendo poco a poco.", now=2) is None


def test_add_note_deduplicates_labelled_paraphrase():
    notes = [{"text": "Me gusta escuchar historias.", "ts": 1}]
    assert add_note(notes, "Hipótesis: Me gusta escuchar historias.", now=2) is None


def test_remove_legacy_diary_discovery_only_when_it_duplicates_a_note():
    diary = [
        {"kind": "discovery", "text": "Airi descubre: Me gusta escuchar historias."},
        {"kind": "discovery", "text": "Airi descubre: Otra cosa útil."},
        {"kind": "meet", "text": "Nos conocimos."},
    ]
    removed = remove_legacy_diary_discoveries(
        diary, [{"text": "Me gusta escuchar historias."}]
    )
    assert removed == 1
    assert [entry["text"] for entry in diary] == [
        "Airi descubre: Otra cosa útil.",
        "Nos conocimos.",
    ]
