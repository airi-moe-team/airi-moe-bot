# Feedback: candidata focalizada contra la indecisión del prompt

- **Feature:** `experimento-prompt-thinking-latencia`
- **Hallazgos:** las candidatas previas aseguraron `wave` con mayor consistencia, pero no redujeron de forma fiable la latencia de `primary`; en `auto` persistieron generaciones largas y hubo una salida al límite de tokens.
- **Severidad:** 1 major.
- **Aprobaciones a resetear al integrar:** requirements, design y tasks.
- **Owner:** agente implementador; el usuario revisa y aprueba los documentos actualizados.

## FB-001 — Evaluar una candidata aislada para GIF y redacción

**Impacto:** Las reglas explícitas que contrastan GIFs pueden sostener la comparación; la obligación implícita de incluir gestos añade otra decisión. Los resultados anteriores muestran que estas indicaciones no controlan consistentemente el coste de la llamada primaria.

**Recomendación:** crear una nueva variante experimental que:

- elija el GIF según la acción/emoción observable de la respuesta, sin contrapuntear ejemplos `wave`/`shy`;
- aclare que las acciones entre asteriscos son opcionales;
- pida directamente una respuesta natural y proporcionada.

Mantener `current`, schema, enums y parámetros de inferencia intactos. Comparar `primary` por separado de reparación y `conversation_review`, con la misma traza/modelo/configuración.

**Targets:** requirements, design, tasks. Añadir pruebas de inmutabilidad de `current`, selección de variante en replay, y medición de tokens/latencia/parseo/truncamiento/reparación.

## Punto de revisión

Confirmar si las tres modificaciones se agrupan en un único brazo nuevo y aprobar el feedback antes de aplicarlo a los documentos normativos. Tras integrar el feedback, requirements/design/tasks requieren revisión y aprobación humana antes de la fase de implementación.
