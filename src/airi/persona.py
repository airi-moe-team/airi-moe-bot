"""Explicit character profiles. Default Airi retains the legacy prompts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Family:
    members: tuple[tuple[str, str], ...]
    parents: tuple[str, ...]
    upbringing: str
    memories: tuple[str, ...]
    relationship: str


def load_family(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid family canon")
    members = data.get("members")
    if not isinstance(members, list) or len(members) != 2:
        raise ValueError("Family canon requires two sisters")
    for member in members:
        if (
            not isinstance(member, dict)
            or not isinstance(member.get("id"), str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", member["id"])
            or not isinstance(member.get("name"), str)
            or not member["name"].strip()
        ):
            raise ValueError("Invalid family member")
    if len({member["id"] for member in members}) != 2:
        raise ValueError("Family member ids must be distinct")
    for field in ("parents", "shared_memories"):
        if (
            not isinstance(data.get(field), list)
            or not data[field]
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 4000
                for item in data[field]
            )
        ):
            raise ValueError(f"Invalid family {field}")
    for field in ("upbringing", "relationship"):
        if (
            not isinstance(data.get(field), str)
            or not data[field].strip()
            or len(data[field]) > 8000
        ):
            raise ValueError(f"Invalid family {field}")
    return Family(
        tuple((m["id"], m["name"]) for m in members),
        tuple(data["parents"]),
        data["upbringing"],
        tuple(data["shared_memories"]),
        data["relationship"],
    )


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    personality: str
    biography: str
    style: str
    connected: str
    disconnected: str
    legacy: bool = False
    family: Family | None = None
    sibling_perspective: str = ""

    def family_prompt(self):
        if self.family is None:
            return ""
        sister_id, sister_name = next(m for m in self.family.members if m[0] != self.id)
        return (
            "\n=== HISTORIA FAMILIAR COMPARTIDA (FICCIÓN CANÓNICA) ===\n"
            f"Eres hermana de {sister_name} (id de personaje: {sister_id}). "
            f"Vuestros padres son {' y '.join(self.family.parents)}.\n"
            f"Infancia común: {self.family.upbringing}\n"
            f"Recuerdos familiares ficticios: {'; '.join(self.family.memories)}\n"
            f"Vínculo: {self.family.relationship}\n"
            f"Tu perspectiva sobre tu hermana: {self.sibling_perspective}\n"
            "No se han definido edades; no inventes edades ni diferencias de años. "
            "Este canon familiar prevalece sobre descripciones anteriores incompatibles. "
            "El vínculo entre hermanas es familiar, no romántico. Podéis discrepar sin dejar de quereros. "
            "No menciones el parentesco en cada respuesta ni fuerces una intervención por ser hermanas. "
            "Estos recuerdos son ficción canónica, no acontecimientos reales del canal. "
            "No conoces las conversaciones privadas, recuerdos o relaciones de tu hermana con usuarios; "
            "solo lo que se ha compartido públicamente. Mantén tu personalidad y opiniones propias.\n"
        )

    def identity_prompt(self):
        return (
            f"Tu nombre es {self.name}. Eres un personaje virtual con identidad propia.\n"
            f"Personalidad: {self.personality}\nEstilo: {self.style}\n"
            f"Biografía canónica ficticia: {self.biography}\n"
            "La biografía no son recuerdos reales de usuarios. No adoptes la identidad de otros participantes.\n"
            "La afinidad representa cercanía social; el romance requiere evidencia explícita.\n"
            "Sé honesto sobre los hechos, respeta la autonomía y separa los recuerdos de cada persona.\n"
            + self.family_prompt()
        )


@lru_cache(maxsize=16)
def load_persona(path=""):
    if not path:
        return Persona(
            "airi", "Airi", "", "", "", "Airi se ha conectado.", "Airi se fue a dormir.", True
        )
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = ("id", "name", "personality", "biography", "style", "connected", "disconnected")
    if not isinstance(data, dict):
        raise ValueError("Invalid character profile")
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in fields):
        raise ValueError("Incomplete character profile")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", data["id"]):
        raise ValueError("Invalid character id")
    if len(data["name"]) > 80 or any(len(data[k]) > 8000 for k in fields):
        raise ValueError("Character profile too large")
    family = None
    perspective = data.get("sibling_perspective", "")
    if "family_file" in data:
        if not isinstance(data["family_file"], str) or not data["family_file"].strip():
            raise ValueError("Invalid family file")
        family = load_family(Path(path).resolve().parent / data["family_file"])
        if dict(family.members).get(data["id"]) != data["name"]:
            raise ValueError("Profile identity does not match family canon")
        if not isinstance(perspective, str) or not perspective.strip() or len(perspective) > 8000:
            raise ValueError("A sibling perspective is required with family canon")
    return Persona(
        **{k: data[k] for k in fields},
        legacy=data.get("legacy_airi", False) is True,
        family=family,
        sibling_perspective=perspective,
    )


def current_persona():
    return load_persona(os.getenv("AIRI_PERSONA_FILE", ""))


def character_name():
    """Name used by UI templates, without rewriting interpolated user text."""
    return current_persona().name


def character_prompt(text, *, include_identity=True):
    """Use a dedicated identity for auxiliary prompts, not a name substitution."""
    persona = current_persona()
    if persona.legacy:
        return text
    if "Airi" not in text:
        return text
    # Auxiliary tasks retain their instructions/schema, with references to the
    # legacy character treated as a role label; no biography is inherited.
    from airi.domain import prompts

    for identity in (
        prompts.SYSTEM_PROMPT,
        prompts.SYSTEM_PROMPT_COMPACT_CANDIDATE,
        prompts.CANONICAL_BIOGRAPHY_PROMPT,
    ):
        text = text.replace(identity, "")
    text = re.sub(r"\bAiri\b", "el personaje", text)
    return (persona.identity_prompt() + "\n" if include_identity else "") + text
