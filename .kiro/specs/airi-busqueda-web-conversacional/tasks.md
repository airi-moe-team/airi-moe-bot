# Tasks — Búsqueda web conversacional

## Fase 1: Contratos y adaptador LLM

- [x] 1.1 Añadir `tools`, `tool_choice` y `LLMMeta.tool_calls` al puerto `LLMClient`.
- [x] 1.2 Implementar el payload de tools en `HttpLlmClient`, normalizar `tool_calls` y rechazar `tools` + `schema` / `tools` + `stream`.
- [x] 1.3 Tests unitarios del adaptador: payload, parseo str/dict, `finish_reason=tool_calls`, errores.

## Fase 2: Búsqueda estructurada

- [x] 2.1 Introducir `WebResult` / `WebSearchNotes` en el puerto y adaptar `BraveSearchClient`.
- [x] 2.2 Eliminar URLs y ranking del extracto; limitar resultados.
- [x] 2.3 Tests de notas: sin URLs, vacío, títulos/extractos.

## Fase 3: Decisión y síntesis

- [x] 3.1 Crear `domain/web_tool.py`: schema `buscar_web`, parseo de `SearchRequest`, render del bloque y metadatos de años.
- [x] 3.2 Crear `services/web_search.py`: decisión con tools, aviso neutro, búsqueda, `WebSearchOutcome`.
- [x] 3.3 Reescribir `WEB_SEARCH_HEADER/FOOTER` y `FACTUAL_HONESTY_PROMPT`; añadir prompt de decisión sin frases de ejemplo.
- [x] 3.4 Tests unitarios de decisión y render.

## Fase 4: Integración en el turno

- [x] 4.1 Sustituir el bloque regex/`_build_search_query` por `WebSearchService` en `ConversationService`.
- [x] 4.2 Eliminar `SEARCH_FAILED_CONTEXT`, `GROUNDED_FALLBACK_TEXT`, `_acknowledges_search_failure` y el reemplazo por grounding.
- [x] 4.3 Mantener el regex solo para la memoria de correcciones, nunca para buscar.
- [x] 4.4 Añadir campos de traza y aviso neutro.
- [x] 4.5 Tests de integración: con búsqueda, sin búsqueda, fallo, allow_web, una sola búsqueda.

## Fase 5: Configuración, regresión y evaluación

- [x] 5.1 `AIRI_WEB_SEARCH` y `WEB_SEARCH_DECISION_MAX_TOKENS`; documentar `--jinja`.
- [x] 5.2 Actualizar fakes, transcripts y tests existentes.
- [x] 5.3 Evaluación semántica de los 8 escenarios (sin frases literales).
- [x] 5.4 Ejecutar suite completa y Ruff.

## Fase 6: Elegibilidad de búsqueda por modo (feedback FB-001)

- [x] 6.1 Ajustar `ConversationService` para permitir tool calling web en turnos `spectator` y `active`, sin cambiar la decisión selectiva `tool_choice="auto"`.
- [x] 6.2 Añadir pruebas de integración que verifiquen disponibilidad en normal/spectator/active y exclusión en citas y turnos proactivos sin petición factual; conservar el caso de `AIRI_WEB_SEARCH=0`.
- [x] 6.3 Ampliar escenarios de evaluación: una pregunta factual en contexto spectator/active debe poder buscarse y una opinión debe poder abstenerse.
- [x] 6.4 Documentar que `airi-replay` valida reproducibilidad, no decisiones de búsqueda web del turno original.
