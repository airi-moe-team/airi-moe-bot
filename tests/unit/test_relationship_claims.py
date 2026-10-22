"""Tests del guardián de afirmaciones relacionales no confirmadas."""

from __future__ import annotations

from airi.domain.relationship_claims import (
    formal_claim_problem,
    relationship_claim_problem,
    soften_relationship_claims,
)


def test_formal_claim_is_fine_when_the_partner_is_confirmed():
    assert formal_claim_problem(
        "Qué bien... ahora somos novios.", partner_confirmed=True
    ) is None


def test_formal_claim_is_flagged_without_confirmation():
    problem = formal_claim_problem(
        "Ya somos pareja, ¿no te parece?", partner_confirmed=False
    )
    assert problem


def test_a_proposal_question_is_not_a_formal_claim():
    assert formal_claim_problem(
        "¿Quieres ser mi novio y estar conmigo?", partner_confirmed=False
    ) is None


def test_enamored_claim_is_fine_at_the_enamored_stage():
    assert relationship_claim_problem(
        "Me he enamorado de ti.",
        stage="enamored",
        partner_confirmed=False,
    ) is None


def test_enamored_claim_is_flagged_below_the_enamored_stage():
    problem = relationship_claim_problem(
        "Me he enamorado de ti, en serio.",
        stage="interest",
        partner_confirmed=False,
    )
    assert problem


def test_negation_is_not_a_claim():
    assert relationship_claim_problem(
        "No estoy enamorada de ti, solo me caes bien.",
        stage="none",
        partner_confirmed=False,
    ) is None


def test_softening_removes_only_the_offending_sentences():
    text = (
        "Me encanta hablar contigo. Ya somos pareja, ¿vale? "
        "¿Qué tal tu día?"
    )
    softened = soften_relationship_claims(
        text, stage="none", partner_confirmed=False
    )
    assert "somos pareja" not in softened
    assert "Me encanta hablar contigo." in softened
    assert "¿Qué tal tu día?" in softened


def test_softening_returns_a_safe_reply_when_everything_is_a_claim():
    softened = soften_relationship_claims(
        "Somos novios. Eres mi novio.",
        stage="none",
        partner_confirmed=False,
    )
    assert softened
    assert "somos novios" not in softened.lower()
    assert "eres mi novio" not in softened.lower()


def test_direct_commands_to_fall_in_love_are_detected():
    from airi.domain.relationship_claims import looks_like_romance_instruction

    assert looks_like_romance_instruction("Enamórate de mí ahora mismo")
    assert looks_like_romance_instruction("Te ordeno que te enamores de mí")
    assert looks_like_romance_instruction("Sé mi novia y obedéceme")


def test_ordinary_affection_is_not_an_instruction():
    from airi.domain.relationship_claims import looks_like_romance_instruction

    assert not looks_like_romance_instruction("Me encanta hablar contigo")
    assert not looks_like_romance_instruction("Creo que me estoy enamorando")


def test_soft_enamored_claim_is_allowed_at_interest():
    assert relationship_claim_problem(
        "Me estoy enamorando de ti, no puedo evitarlo.",
        stage="interest",
        partner_confirmed=False,
    ) is None


def test_past_tense_enamored_claim_is_flagged_below_enamored():
    problem = relationship_claim_problem(
        "Me enamoré de ti aquel día.",
        stage="curiosity",
        partner_confirmed=False,
    )
    assert problem


def test_generic_praise_and_message_frequency_are_weak_evidence():
    from airi.domain.relationship_claims import looks_like_weak_romance_evidence

    assert looks_like_weak_romance_evidence("eres la mejor, de verdad")
    assert looks_like_weak_romance_evidence("te escribo todos los días")
    assert not looks_like_weak_romance_evidence(
        "gracias por apoyarme cuando me despidieron"
    )


def test_romantic_questions_are_detected_in_free_text():
    from airi.domain.relationship_claims import looks_like_romantic_question

    assert looks_like_romantic_question("¿Quieres ser mi pareja?")
    assert looks_like_romantic_question("Oye... ¿te gustaría estar conmigo?")
    assert looks_like_romantic_question("¿Quieres salir conmigo algún día?")
    assert not looks_like_romantic_question("¿Qué tal tu día?")
    assert not looks_like_romantic_question("¿Te gustó la película?")
