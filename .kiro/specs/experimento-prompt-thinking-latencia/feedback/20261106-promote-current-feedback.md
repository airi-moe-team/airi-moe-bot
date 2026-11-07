# Feedback: promoción de la guía experimental a producción

- **Feature:** `experimento-prompt-thinking-latencia`
- **Severidad:** 1 major.
- **Aprobaciones a resetear al integrar:** requirements, design y tasks.
- **Owner:** agente implementador; el usuario revisa y aprueba los documentos actualizados.

## FB-001 — Promover la guía decision-light a `current`

**Contexto:** El usuario solicita llevar al system prompt real las reglas que hasta ahora se probaron en `decision_light_candidate`. Esto cambia el alcance aprobado, que mantenía `current` sin cambios.

**Actualización propuesta:**

- GIF: valor canónico permitido seleccionado según la reacción observable, sin forzar coincidencia con `mood.label`.
- Respuesta: formulación cotidiana directa y proporcionada.
- Gestos: acciones narrativas opcionales.
- Harness: conservar `smile → happy` y `neutral → nod`; `shy` ya es canónico.

Mantener intactos el schema y las categorías canónicas. La normalización de alias no se presenta como una solución al razonamiento extenso ni a reparaciones por JSON inválido.

**Siguiente punto de revisión:** aprobar los documentos actualizados antes de cambiar `current` en código.
