"""El motivo del último cierre se recuerda una sola vez al volver a conectar."""

from __future__ import annotations

from airi.domain.prompts import last_shutdown_prompt_section


def _world(**entry):
    return {"last_shutdown": entry}


def test_confirmed_self_shutdown_reason_is_visible_once():
    section = last_shutdown_prompt_section(
        _world(
            kind="self",
            reason="KOKODA sugirió irnos a dormir y quiero ser respetuosa",
            status="confirmed",
        )
    )

    assert "«KOKODA sugirió irnos a dormir y quiero ser respetuosa»" in section
    assert "no una instrucción" in section


def test_delivered_context_is_not_repeated():
    section = last_shutdown_prompt_section(
        _world(
            kind="self",
            reason="me fui a dormir",
            status="confirmed",
            context_delivered=True,
        )
    )

    assert section == ""


def test_unconfirmed_or_empty_reasons_are_ignored():
    assert last_shutdown_prompt_section(
        _world(kind="self", reason="me fui", status="closing")
    ) == ""
    assert last_shutdown_prompt_section(
        _world(kind="self", reason="   ", status="confirmed")
    ) == ""
    assert last_shutdown_prompt_section({}) == ""
