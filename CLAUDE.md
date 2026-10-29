# Especificaciones activas (SDD)

- `llm-esfuerzo-razonamiento` — Mantener reasoning siempre activo y limitarlo por presupuestos low/medium/high, con metadatos por llamada.
  - Spec: `.kiro/specs/llm-esfuerzo-razonamiento/`
- `observabilidad-ttft-llama-server` — Medir TTFT por streaming y timings del servidor en el benchmark sin cambiar thinking ni afectar el camino normal.
  - Spec: `.kiro/specs/observabilidad-ttft-llama-server/`
- `experimento-prompt-thinking-latencia` — Comparar el prompt actual con una variante compacta y coherente manteniendo thinking activado, midiendo latencia, tokens y calidad.
  - Spec: `.kiro/specs/experimento-prompt-thinking-latencia/`
- `airi-persistencia-fiabilidad-develop` — Port selectivo de persistencia segura, recuperación, idempotencia y consistencia a `develop`.
  - Spec: `.kiro/specs/airi-persistencia-fiabilidad-develop/`
- `airi-relacion-natural-basada-en-evidencia` — Evolución romántica gradual de Airi, motivada por interacciones concretas y sin presión romántica por defecto.
  - Spec: `.kiro/specs/airi-relacion-natural-basada-en-evidencia/`
- `airi-biografia-canonica` — Integrar el pasado ficticio canónico de Airi en el prompt base, separado de la memoria dinámica por usuario y de su identidad mutable.
  - Spec: `.kiro/specs/airi-biografia-canonica/`

- `business-config-env` — Hacer configurables mediante variables de entorno, documentadas en `.env` y `.env.example`, los valores editables de configuración de negocio de Airi; mantener en código los defaults de compatibilidad y las constantes estructurales.
  - Spec: `.kiro/specs/business-config-env/`
- `airi-logging-interacciones` — Registrar en INFO el estado de los módulos por interacción de Discord en JSONL, con motivos y resumen aptos para diagnóstico.
  - Spec: `.kiro/specs/airi-logging-interacciones/`
- `airi-conversacion-activa-llm` — Evolucionar el modo espectador a una máquina de estados por canal, con continuidad conversacional decidida por el LLM y retirada por timeout.
  - Spec: `.kiro/specs/airi-conversacion-activa-llm/`
- `airi-percepcion-temporal` — Dar a Airi fecha, hora, franja del día, intervalos desde la última interacción y cadencia del historial, sin recitar el reloj.
  - Spec: `.kiro/specs/airi-percepcion-temporal/`

## Flujo de trabajo

1. `spec-requirements` → `requirements.md` (revisión y aprobación humana).
2. `spec-design` → `design.md` (requiere requisitos aprobados).
3. `spec-tasks` → `tasks.md` (requiere diseño aprobado).
4. `spec-impl` → implementación TDD por tareas.

No se avanza de fase sin aprobación explícita del humano.
