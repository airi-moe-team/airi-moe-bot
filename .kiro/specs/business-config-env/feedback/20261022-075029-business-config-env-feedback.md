# Feedback de desarrollo — business-config-env

- Elementos: 1 (1 major)
- Aprobaciones a reiniciar al aplicar: diseño y tareas. Los requisitos no cambian.
- Responsable: implementador; el usuario revisa y aprueba los documentos actualizados.

## FB-001 — Centralizar la carga de dotenv en todos los entrypoints

**Severidad:** major  
**Impacto:** La implementación carga dotenv solo al iniciar el bot. Los entrypoints directos `airi-trace` y `airi-replay` pueden importar constantes del dominio antes de cargar `.env`. Además, existe una decisión previa de centralizar el bootstrap en todos los entrypoints.

**Actualización recomendada para diseño:** Crear `airi.env_boot` para cargar dotenv y asegurar que se importe antes que cualquier otro módulo `airi.*` desde `airi.__main__`, `airi.observability.cli` y `airi.observability.replay`. Mantener lazy los handlers de `__main__` y documentar la compatibilidad con los entrypoints directos.

**Actualización recomendada para tareas:** Añadir la creación e integración del módulo central y pruebas aisladas de orden de importación para `airi`, `airi-trace` y `airi-replay`.

**Responsable:** Implementador. El usuario revisa y aprueba diseño y tareas actualizados.

**Próximo checkpoint:** Aplicar el feedback, verificar el estado SDD, actualizar los documentos y solicitar aprobación antes de continuar.
