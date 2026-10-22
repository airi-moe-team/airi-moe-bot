"""Reanudación de respuestas confirmadas no publicadas (tarea 6.1)."""

from __future__ import annotations

import asyncio

from airi.domain.turns import TurnStatus
from airi.services.publication import PublicationResumer
from airi.services.state import AppState
from airi.services.turn_journal import TurnJournal

NOW = 1000.0


def make_journal():
    state = AppState(world={"season": 1})
    journal = TurnJournal(state)
    claim = journal.claim(7, ["100"], now=NOW - 10)
    journal.mark_committed(claim.turn_key, "respuesta pendiente", now=NOW - 5)
    return journal, claim.turn_key


def run(coro):
    return asyncio.run(coro)


def test_resume_publishes_and_marks_published():
    journal, turn_key = make_journal()
    published = []

    async def publisher(record):
        published.append(record.reply_text)

    count = run(
        PublicationResumer(journal, ttl=900, clock=lambda: NOW).resume(publisher)
    )

    assert count == 1
    assert published == ["respuesta pendiente"]
    assert journal.get(turn_key).status is TurnStatus.PUBLISHED


def test_resume_skips_expired_records():
    journal, turn_key = make_journal()
    published = []

    async def publisher(record):
        published.append(record)

    count = run(
        PublicationResumer(journal, ttl=1, clock=lambda: NOW).resume(publisher)
    )

    assert count == 0
    assert published == []
    assert journal.get(turn_key).status is TurnStatus.COMMITTED


def test_resume_keeps_record_when_publish_fails():
    journal, turn_key = make_journal()

    async def broken(record):
        raise RuntimeError("Discord caído")

    count = run(
        PublicationResumer(journal, ttl=900, clock=lambda: NOW).resume(broken)
    )
    assert count == 0
    assert journal.get(turn_key).status is TurnStatus.COMMITTED
