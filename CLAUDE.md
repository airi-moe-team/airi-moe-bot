# Especificaciones activas (SDD)

- `airi-persistencia-fiabilidad-develop` — Port selectivo de persistencia segura, recuperación, idempotencia y consistencia a `develop`.
  - Spec: `.kiro/specs/airi-persistencia-fiabilidad-develop/`
- `airi-relacion-natural-basada-en-evidencia` — Evolución romántica gradual de Airi, motivada por interacciones concretas y sin presión romántica por defecto.
  - Spec: `.kiro/specs/airi-relacion-natural-basada-en-evidencia/`

- `business-config-env` — Hacer configurables mediante variables de entorno, documentadas en `.env` y `.env.example`, los valores editables de configuración de negocio de Airi; mantener en código los defaults de compatibilidad y las constantes estructurales.
  - Spec: `.kiro/specs/business-config-env/`
- `airi-logging-interacciones` — Registrar en INFO el estado de los módulos por interacción de Discord en JSONL, con motivos y resumen aptos para diagnóstico.
  - Spec: `.kiro/specs/airi-logging-interacciones/`
- `airi-conversacion-activa-llm` — Evolucionar el modo espectador a una máquina de estados por canal, con continuidad conversacional decidida por el LLM y retirada por timeout.
  - Spec: `.kiro/specs/airi-conversacion-activa-llm/`

## Flujo de trabajo

1. `spec-requirements` → `requirements.md` (revisión y aprobación humana).
2. `spec-design` → `design.md` (requiere requisitos aprobados).
3. `spec-tasks` → `tasks.md` (requiere diseño aprobado).
4. `spec-impl` → implementación TDD por tareas.

No se avanza de fase sin aprobación explícita del humano.
