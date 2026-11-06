# Especificaciones activas (SDD)

- `llm-esfuerzo-razonamiento` — Mantener reasoning siempre activo con presets cerrados `auto`, `low`, `medium` y `high`, y metadatos por llamada.
  - Spec: `.kiro/specs/llm-esfuerzo-razonamiento/`
- `airi-temperatura-proveedor` — Dejar que cada proveedor LLM aplique su temperatura predeterminada, sin controlar temperatura desde Airi.
  - Spec: `.kiro/specs/airi-temperatura-proveedor/`
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
- `airi-cita-decision` — Permitir invitar a Airi a cualquier afinidad y hacer que ella decida si acepta antes de iniciar la cita.
  - Spec: `.kiro/specs/airi-cita-decision/`

- `business-config-env` — Hacer configurables mediante variables de entorno, documentadas en `.env` y `.env.example`, los valores editables de configuración de negocio de Airi; mantener en código los defaults de compatibilidad y las constantes estructurales.
  - Spec: `.kiro/specs/business-config-env/`
- `airi-logging-interacciones` — Registrar en INFO el estado de los módulos por interacción de Discord en JSONL, con motivos y resumen aptos para diagnóstico.
  - Spec: `.kiro/specs/airi-logging-interacciones/`
- `airi-conversacion-activa-llm` — Evolucionar el modo espectador a una máquina de estados por canal, con continuidad conversacional decidida por el LLM y retirada por timeout.
  - Spec: `.kiro/specs/airi-conversacion-activa-llm/`
- `airi-percepcion-temporal` — Dar a Airi fecha, hora, franja del día, intervalos desde la última interacción y cadencia del historial, sin recitar el reloj.
- `airi-reparaciones-parseo-calidad` — Fusionar las 5 reparaciones del turno en 2 políticas (parse_repair + quality_repair) con revisión del borrador, añadir conversation_review semántico para coherencia de hilo, y parches deterministas (ChatML, OOC, strip_leaving_claims).  - Spec: `.kiro/specs/airi-percepcion-temporal/`
- `airi-busqueda-web-conversacional` — Sustituir el disparador por regex por tool calling nativo decidido por el modelo; síntesis reactiva con voz propia, duda ante contradicciones y grounding solo en traza.
  - Spec: `.kiro/specs/airi-busqueda-web-conversacional/`
- `airi-replay-conductual` — Añadir replay conductual con resultados capturados opt-in y replay live explícito, preservando aislamiento y privacidad por defecto.
  - Spec: `.kiro/specs/airi-replay-conductual/`
- `airi-payload-llm` — Capturar opt-in el payload LLM efectivo como artefacto local lateral, vinculado a la traza y protegido por privacidad.
  - Spec: `.kiro/specs/airi-payload-llm/`

## Flujo de trabajo

1. `spec-requirements` → `requirements.md` (revisión y aprobación humana).
2. `spec-design` → `design.md` (requiere requisitos aprobados).
3. `spec-tasks` → `tasks.md` (requiere diseño aprobado).
4. `spec-impl` → implementación TDD por tareas.

No se avanza de fase sin aprobación explícita del humano.
