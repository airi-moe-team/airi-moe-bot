"""Tests del match por palabra completa del keyword de fin de cita (1.1).

Sin esta comprobación, "fin" casaba dentro de "final", "afinidad",
"definitivamente", "infinito" o "fingir" y cerraba la cita en el turno 1.
"""

from airi.domain.constants import DATE_END_KEYWORD_MIN_TURNS
from airi.domain.dates import new_date_session, step_date
from airi.domain.texts import end_keyword_hit

NOW = 1_000_000.0


# --- end_keyword_hit --------------------------------------------------------


def test_ignores_substring_matches():
    assert end_keyword_hit("al final me lo pasé genial") is None
    assert end_keyword_hit("me encanta nuestra afinidad") is None
    assert end_keyword_hit("definitivamente quiero repetir") is None
    assert end_keyword_hit("te lo digo con infinito cariño") is None
    assert end_keyword_hit("voy a fingir que no lo vi") is None


def test_matches_whole_words_and_phrases():
    assert end_keyword_hit("adiós, me voy") == "adiós"
    assert end_keyword_hit("se acabó") == "se acabó"
    assert end_keyword_hit("esto es el fin") == "fin"
    assert end_keyword_hit("hasta luego") == "hasta luego"


def test_rejects_non_string_or_empty():
    assert end_keyword_hit(None) is None
    assert end_keyword_hit("") is None
    assert end_keyword_hit(123) is None


def test_is_case_insensitive():
    assert end_keyword_hit("ADIÓS") == "adiós"


# --- gate por turnos mínimos ------------------------------------------------


def test_keyword_does_not_close_before_min_turns():
    session = new_date_session("paseo", 40, now=NOW)

    # Turno 1: la palabra está, pero aún no puede cerrar.
    assert DATE_END_KEYWORD_MIN_TURNS > 1
    state, event = step_date(session, points=40, end_keyword=True, now=NOW)

    assert event == "continue"
    assert session["state"] == "active"


def test_keyword_closes_from_min_turns_onwards():
    session = new_date_session("paseo", 40, now=NOW)
    session["turns"] = DATE_END_KEYWORD_MIN_TURNS - 1

    state, event = step_date(session, points=40, end_keyword=True, now=NOW)

    assert event == "ending"
    assert session["state"] == "final_scene"
