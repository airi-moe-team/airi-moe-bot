# Especificaciones activas (SDD)

- `airi-persistencia-fiabilidad-develop` — Port selectivo de persistencia segura, recuperación, idempotencia y consistencia a `develop`.
  - Spec: `.kiro/specs/airi-persistencia-fiabilidad-develop/`

## Flujo de trabajo

1. `spec-requirements` → `requirements.md` (revisión y aprobación humana).
2. `spec-design` → `design.md` (requiere requisitos aprobados).
3. `spec-tasks` → `tasks.md` (requiere diseño aprobado).
4. `spec-impl` → implementación TDD por tareas.

No se avanza de fase sin aprobación explícita del humano.
