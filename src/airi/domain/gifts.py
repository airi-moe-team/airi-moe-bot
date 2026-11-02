"""Regalos: catálogo y efectos sobre la afinidad."""

from __future__ import annotations

from airi.domain.affinity import clamp_delta

# Regalos: cada uno con sus etiquetas (para cruzar con los gustos de Airi).
GIFTS = {
    "flores": {"tags": ["romantico", "tierno"], "base": 2},
    "rosas": {"tags": ["romantico", "tierno"], "base": 3},
    "chocolate": {"tags": ["comida", "tierno"], "base": 2},
    "peluche": {"tags": ["tierno"], "base": 2},
    "collar": {"tags": ["romantico", "caro"], "base": 3},
    "perfume": {"tags": ["romantico", "caro"], "base": 3},
    "libro": {"tags": ["intelectual"], "base": 2},
    "videojuego": {"tags": ["divertido"], "base": 2},
    "cafe": {"tags": ["comida"], "base": 1},
    "pizza": {"tags": ["comida"], "base": 1},
    "carta": {"tags": ["romantico", "tierno"], "base": 3},
}

# ============================================================
# REGALOS
# ============================================================


def gift_effect(item, preferences, recent_gifts=None):
    """Cambio de afinidad que produce un regalo según los gustos de Airi."""
    key = (item or "").strip().lower()
    gift = GIFTS.get(key)
    if not gift:
        return 0

    recent = {str(i).strip().lower() for i in (recent_gifts or [])}
    if key in recent:
        return 0  # Se aburre de recibir lo mismo.

    preferences = preferences if isinstance(preferences, dict) else {}
    loves = {
        str(t).lower()
        for t in (
            list(preferences.get("loves") or [])
            + list(preferences.get("comforts") or [])
        )
    }
    dislikes = {str(t).lower() for t in (preferences or {}).get("dislikes", [])}
    tags = {str(t).lower() for t in gift.get("tags", [])}

    effect = int(gift.get("base", 0))
    effect += len(tags & loves)
    if tags & dislikes:
        effect -= 3
    return clamp_delta(effect)
