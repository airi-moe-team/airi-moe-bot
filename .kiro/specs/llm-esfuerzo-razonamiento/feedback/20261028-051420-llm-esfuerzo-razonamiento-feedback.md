# Feedback de implementación: llm-esfuerzo-razonamiento

- Elementos: 1 (1 major)
- Aprobaciones a reiniciar: diseño y tareas; requisitos no cambian.
- Responsable: implementación de la feature.

## FB-LLM-001 — Enviar reasoning_effort mediante chat_template_kwargs

**Contexto:** El llama-server activo respondió HTTP 200 al campo superior `reasoning_effort`. Tres llamadas deterministas con `low`, `medium` y `high` devolvieron el mismo `finish_reason`, `completion_tokens` y longitud de `reasoning`; no hay evidencia observable de que el campo superior se aplique. La documentación oficial de llama.cpp describe el esfuerzo como valor del chat template y permite enviar parámetros del template mediante `chat_template_kwargs`.

**Actualización recomendada:** Enviar `chat_template_kwargs: {"reasoning_effort": nivel}` en modo global graduado y en overrides locales. En `auto` + `quick_turn`, combinar ambas opciones como `{"enable_thinking": false}`; el esfuerzo explícito debe prevalecer y no desactivar thinking. Dejar `reasoning_effort` nullable en los metadatos del cliente para el valor enviado, no como confirmación de obediencia.

**Validación:** repetir una prueba live pequeña y no destructiva contra el servidor ya activo. No reiniciar ni reconfigurar el servidor; no guardar ni imprimir `reasoning_content`.

**Pregunta pendiente:** el servidor instalado sirve Qwen3.5-9B, mientras que la configuración de ejemplo menciona Qwen3.6; por tanto, resultados live aplican solo a ese modelo/versión y no generalizan.
