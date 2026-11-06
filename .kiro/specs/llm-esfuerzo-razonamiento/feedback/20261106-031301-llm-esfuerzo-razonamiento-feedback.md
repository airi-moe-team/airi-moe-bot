# Feedback: perfil de generación

- Elementos: 1 (major: 1)
- Aprobaciones que requieren revisión: requirements, design y tasks.
- Propietario: mantenimiento de `llm-esfuerzo-razonamiento`.

## FB-LLM-GEN-001 — Agrupar topes de salida en perfil de generación

Los límites general y breve (`LLM_MAX_TOKENS`, `LLM_SHORT_MAX_TOKENS`) son parámetros relacionados y no deberían ajustarse por separado. Se introduce `LLM_GENERATION_PROFILE=balanced`, con topes 8182/2048, manteniéndolo independiente de `LLM_THINKING_MODE`. La detección de turno breve decide cuál aplicar. Los overrides internos explícitos se conservan y el adaptador sigue reservando espacio para reasoning más 512 tokens.

Requirements, design y tasks se actualizaron junto con implementación y documentación. Próximo checkpoint: revisión humana de los documentos SDD modificados.
