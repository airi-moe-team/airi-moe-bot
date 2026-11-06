# Feedback — airi-payload-llm

- Elementos: 1 (major)
- Aprobaciones a reiniciar: requirements, design y tasks.
- Documentos de spec presentes: requirements.md, design.md y tasks.md.
- Responsable: agente incorpora cambios; usuario revisa y aprueba cada fase.

## FB-001 — Guardar request y response como artefactos enlazados y reducir la traza a índice

**Contexto:** La implementación actual persiste la respuesta cruda en `raw_llm` dentro de la traza y solo captura el request en el sidecar. El usuario aprobó que la respuesta completa pase a un artefacto enlazado.

**Cambio propuesto:** Guardar request/response en sidecars separados bajo `private-llm-artifacts/`, cada uno con checksum y enlace común por turno/llamada. La traza conserva resultado final visible y metadatos/referencias, no `raw_llm` completo. El nombre de configuración debe cubrir ambos tipos de artefacto.

**Siguiente checkpoint:** actualizar y revisar requirements, después design y tasks; no implementar hasta aprobar los documentos revisados.
