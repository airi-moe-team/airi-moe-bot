# Feedback — airi-payload-llm

- Elementos: 1 (minor)
- Aprobaciones a reiniciar: ninguna; los requisitos aún no están aprobados.
- Documentos aún inexistentes: `design.md`, `tasks.md`.
- Responsable: agente actual incorpora el ajuste; usuario revisa los requisitos.

## FB-001 — No exigir advertencia ni permisos restrictivos para el sidecar local

**Contexto:** El usuario indicó que el artefacto será local, por lo que no considera necesarias una advertencia sobre datos sensibles ni una exigencia de permisos locales restrictivos.

**Cambio propuesto:** Requerir payload JSON efectivo íntegro en sidecar local cuando opt-in; excluir credenciales/cabeceras; quitar advertencia y requisito funcional POSIX.
