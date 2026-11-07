from airi.domain.prompts import (
    AFFINITY_TONE_HINTS,
    COMPACT_OUTPUT_PROMPT,
    OUTPUT_CONTRACT_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_COMPACT_CANDIDATE,
)


def test_new_acquaintances_get_neutral_respectful_tone_without_assumed_closeness():
    tone = AFFINITY_TONE_HINTS["Desconocida"].lower()

    assert "neutral" in tone
    assert "respetuoso" in tone
    assert "cordial" not in tone
    assert "cálida" not in tone
    assert "sin asumir cercanía" in tone


def test_full_and_compact_personalities_allow_autonomy_without_service_reflex():
    for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_COMPACT_CANDIDATE):
        lowered = prompt.lower()
        assert "no tienes que validar, elogiar, agradecer, tranquilizar" in lowered
        assert "ofrecer ayuda por reflejo" in lowered
        assert "no adoptes un tono servicial por defecto" in lowered
        assert "respeto básico" in lowered


def test_full_and_compact_contracts_make_warmth_contextual_and_use_neutral_example():
    for prompt in (OUTPUT_CONTRACT_PROMPT, COMPACT_OUTPUT_PROMPT):
        lowered = prompt.lower()
        assert "no una obligación de trato cordial o cálido" in lowered
        assert "me parece una idea genial" not in lowered
        assert '"reply":"no me convence."' in lowered
