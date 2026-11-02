"""El sistema de regalos respeta los tipos de preferencia de Airi."""

from airi.domain.gifts import gift_effect


def test_stable_likes_and_comforts_can_improve_a_matching_gift():
    base = gift_effect("rosas", {})
    liked = gift_effect("rosas", {"loves": ["romantico"]})
    comforting = gift_effect("rosas", {"comforts": ["tierno"]})
    assert liked == base + 1
    assert comforting == base + 1


def test_curiosity_does_not_count_as_a_liking_or_experience():
    base = gift_effect("rosas", {})
    curious = gift_effect("rosas", {"curious_about": ["romantico"]})
    assert curious == base


def test_boundaries_do_not_score_gifts_as_positive_or_negative_tastes():
    base = gift_effect("rosas", {})
    boundaries = gift_effect("rosas", {"boundaries": ["romantico"]})
    assert boundaries == base


def test_actual_dislikes_reduce_matching_gift_effect():
    base = gift_effect("rosas", {})
    disliked = gift_effect("rosas", {"dislikes": ["romantico"]})
    assert disliked == max(-5, base - 3)
