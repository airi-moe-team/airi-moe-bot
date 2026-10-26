"""Tests del dominio de memorias (airi.domain.memories + fachada bot)."""

from airi.domain import memories as domain_memories

NOW = 1_000_000.0


def test_add_memory_saves_and_limits():
    data = {}
    assert domain_memories.add_memory(data, 1, "Le encanta el ramen", now=NOW) is True
    assert domain_memories.add_memory(data, 1, "", now=NOW) is False
    entries = domain_memories.user_memories(data, 1)
    assert len(entries) == 1
    assert entries[0]["created_at"] == NOW


def test_add_memory_rejects_exact_duplicate():
    data = {}
    domain_memories.add_memory(data, 1, "Vive en Madrid con su hermana", now=NOW)
    assert domain_memories.add_memory(data, 1, "Vive en Madrid con su hermana",
                                       now=NOW) is False
    assert domain_memories.add_memory(data, 1, "vive en madrid con su hermana",
                                       now=NOW) is False


def test_add_memory_partial_short_tokens_are_not_duplicates():
    # Caso regresión: "Dato 1" vs "Dato 10" no deben fusionarse.
    data = {}
    assert domain_memories.add_memory(data, 1, "Dato 1", now=NOW) is True
    assert domain_memories.add_memory(data, 1, "Dato 10", now=NOW) is True
    assert len(domain_memories.user_memories(data, 1)) == 2


def test_add_memory_partial_long_overlap_is_duplicate():
    data = {}
    domain_memories.add_memory(data, 1, "Trabaja en una librería del centro", now=NOW)
    assert domain_memories.add_memory(data, 1, "trabaja en una librería", now=NOW) is False


def test_add_memory_evicts_oldest_beyond_limit():
    data = {}
    for i in range(20):
        domain_memories.add_memory(data, 1, f"memoria número {i} con texto largo",
                                   now=NOW, max_items=3)
    entries = domain_memories.user_memories(data, 1)
    assert len(entries) == 3
    assert entries[0]["text"].endswith("17 con texto largo")


def test_forget_by_index_and_all():
    data = {}
    for i in range(3):
        domain_memories.add_memory(data, 1, f"recuerdo largo número {i}", now=NOW)
    assert domain_memories.forget_memory(data, 1, 2) is True
    entries = domain_memories.user_memories(data, 1)
    assert len(entries) == 2
    assert domain_memories.forget_memory(data, 1, 99) is False
    assert domain_memories.forget_memory(data, 1) is True
    assert domain_memories.user_memories(data, 1) == []
    assert domain_memories.forget_memory(data, 1) is False


def test_process_memory_action_save_forget_and_none():
    data = {}
    assert domain_memories.process_memory_action(data, 1, "none", now=NOW) is False
    assert domain_memories.process_memory_action(data, 1, "  ", now=NOW) is False
    assert domain_memories.process_memory_action(data, 1, None, now=NOW) is False
    assert domain_memories.process_memory_action(data, 1, "Tiene un gato largo",
                                                  now=NOW) is True
    # Olvidar devuelve False (ninguna memoria NUEVA) pero borra.
    assert domain_memories.process_memory_action(data, 1, "olvidar: 1", now=NOW) is False
    assert domain_memories.user_memories(data, 1) == []


def test_preference_correction_supersedes_the_previous_topic():
    data = {}
    domain_memories.add_memory(
        data,
        1,
        "Le encanta el flan.",
        now=NOW,
        source_text="Mi postre favorito es el flan.",
    )
    correction = domain_memories.extract_preference_correction(
        "No, me equivoqué: mi postre favorito es el tiramisú."
    )
    assert correction is not None
    assert correction.topic_key == "postre"
    assert correction.value == "el tiramisú"
    assert domain_memories.apply_preference_correction(
        data, 1, correction, now=NOW + 10
    ) is True

    entries = domain_memories.user_memories(data, 1)
    assert len(entries) == 2
    assert entries[0]["status"] == domain_memories.SUPERSEDED
    assert entries[1]["status"] == domain_memories.ACTIVE
    assert entries[1]["topic"] == "postre"
    assert entries[1]["source"] == "correction"
    assert entries[0]["updated_at"] == NOW + 10
    assert [e["text"] for e in domain_memories.active_memories(entries)] == [
        "Su postre favorito es el tiramisú."
    ]


def test_preference_correction_links_legacy_memory_without_topic():
    data = {"1": [{"text": "Le encanta el flan.", "created_at": NOW}]}
    correction = domain_memories.extract_preference_correction(
        "No, me equivoqué: mi postre favorito es el tiramisú."
    )
    assert domain_memories.apply_preference_correction(
        data,
        1,
        correction,
        now=NOW + 10,
        previous_text="Mi postre favorito es el flan.",
    ) is True
    entries = domain_memories.user_memories(data, 1)
    assert entries[0]["status"] == domain_memories.SUPERSEDED
    assert [e["text"] for e in domain_memories.active_memories(entries)] == [
        "Su postre favorito es el tiramisú."
    ]


def test_preference_correction_requires_an_explicit_marker():
    assert domain_memories.extract_preference_correction(
        "Mi postre favorito es el tiramisú."
    ) is None
    assert domain_memories.extract_preference_correction(
        "No, me equivoqué: mi postre favorito es el tiramisú."
    ) is not None


def test_forget_indexes_only_active_memories():
    data = {}
    domain_memories.add_memory(
        data, 1, "Le encanta el flan.", now=NOW,
        source_text="Mi postre favorito es el flan.",
    )
    correction = domain_memories.extract_preference_correction(
        "No, me equivoqué: mi postre favorito es el tiramisú."
    )
    domain_memories.apply_preference_correction(data, 1, correction, now=NOW + 10)
    assert domain_memories.forget_memory(data, 1, 1) is True
    entries = domain_memories.user_memories(data, 1)
    assert [e["text"] for e in domain_memories.active_memories(entries)] == []
    assert entries[0]["status"] == domain_memories.SUPERSEDED


def test_relevant_memories_matches_the_current_topic_only():
    entries = [
        {
            "text": "Su postre favorito es el tiramisú.",
            "topic": "postre",
            "status": domain_memories.ACTIVE,
        },
        {
            "text": "Tiene una mascota llamada Nube.",
            "topic": "mascota",
            "status": domain_memories.ACTIVE,
        },
        {
            "text": "Le encanta el flan.",
            "topic": "postre",
            "status": domain_memories.SUPERSEDED,
        },
    ]
    matches = domain_memories.relevant_memories(
        entries, "¿Qué postre crees que me gusta?"
    )
    assert [entry["text"] for entry in matches] == [
        "Su postre favorito es el tiramisú."
    ]

