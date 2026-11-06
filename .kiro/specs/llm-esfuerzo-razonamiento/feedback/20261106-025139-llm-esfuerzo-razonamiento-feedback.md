# Feedback: presets cerrados de razonamiento

- Elementos: 1 (major: 1)
- Aprobaciones que requieren nueva revisión: requirements, design y tasks.
- Propietario: mantenimiento de la feature `llm-esfuerzo-razonamiento`.

## FB-LLM-PRESET-001 — Consolidar modos de razonamiento en presets cerrados

`on` duplicaba el caso de `auto` en turnos normales, mientras que variables independientes podían cambiar el significado de `low`, `medium` y `high`. El contrato queda en cuatro presets: `auto`, `low`, `medium`, `high`; presupuestos fijos agrupados de 256, 1024 y 4096 tokens, respectivamente; `auto` usa `low` en turnos rápidos y el default del servidor en turnos normales. Las antiguas variables de presupuesto dejan de alterar los presets.

Cambios recomendados y aplicados en requisitos, diseño y tareas, además de adaptador, benchmark, tests y documentación de entorno. Checkpoint: revisión humana de los documentos actualizados.
