# Feedback: traits perceptibles y con evolución contextual

- **Feature:** `airi-interaccion-natural`
- **Fecha:** 2026-10-31
- **Elementos:** 1 major
- **Aprobaciones a reiniciar:** requirements, design y tasks
- **Responsable:** desarrollo; revisión/aprobación documental por la persona usuaria

## FB-TRAITS-VISIBLE-CHANGES — Hacer perceptibles y mejor fundamentadas las actualizaciones automáticas de traits

**Severidad:** major  
**Ámbitos:** requirements, design, tasks; especialmente R9.

Los traits tienen una fuente dinámica para su intensidad, pero la reflexión automática tiene baja frecuencia y el prompt de reflexión no aprovecha los datos de modelo, diario y notas que recibe. Como resultado, hay pocas oportunidades de cambio y poco contexto para justificarlo.

### Cambio propuesto

- Incluir los traits actuales y evidencia reciente relevante en el prompt de reflexión, acotando el contexto y conservando el sentinel cuando no haya motivo genuino para cambiar.
- Explicar cómo niveles 1–5 alteran tendencias observables sin convertirlas en órdenes ni imponerse a la intención/contexto de la conversación.
- Probar por defecto reflexión cada 5 interacciones y cooldown mínimo de 30 minutos, configurables.
- Conservar evidencia obligatoria, rate limit diario por trait y pruebas que confirmen que el cambio persistido llega al siguiente prompt conversacional.

### Aprobación solicitada

Aprobada por la persona usuaria: cadencia por defecto de 5 interacciones y 30 minutos, manteniendo el máximo de un cambio diario por trait. Los documentos se actualizaron y requieren revisión/aprobación formal antes de implementar. Tras la revisión, integrar el feedback en requirements/design/tasks y obtener aprobación humana antes de iniciar TDD/implementación.
