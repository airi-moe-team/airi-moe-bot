# Informe de feedback — airi-busqueda-web-conversacional

- **Fecha:** 2026-11-02
- **Elementos:** 1 (1 major)
- **Aprobaciones a reiniciar al aplicar:** requirements, design y tasks, porque los tres documentos necesitan reflejar la nueva elegibilidad y su cobertura de pruebas.
- **Propietario propuesto:** responsable de Airi (actualización SDD e implementación); revisión/aprobación: usuario.

## FB-001 — Permitir decisión de búsqueda web en turnos spectator y active

**Severidad:** major  
**Contexto e impacto:** El requisito 6.2 actual excluye el modo espectador. La traza 25864c85187b evidencia que Airi no pudo verificar una frase factual contextual al despertar por mención.  
**Recomendación:** Ofrecer búsqueda nativa en turnos normal, spectator y active, manteniendo la decisión selectiva del modelo (`tool_choice=auto`). No iniciar búsquedas en cada turno por defecto. Mantener fuera los turnos proactivos sin petición factual y dejar explícitas las demás exclusiones deliberadas (por ejemplo, citas). El replay sigue aislado de servicios externos y no sirve para evaluar la decisión web original.

### Actualizaciones propuestas

- **Requirements:** añadir elegibilidad en modos normal/spectator/active y precisar que habilitar la herramienta no fuerza la búsqueda.
- **Design:** separar elegibilidad de decisión de uso; documentar exclusiones y limitación del replay.
- **Tasks:** añadir cobertura de spectator/active y exclusiones, y escenarios de evaluación factual frente a opinión.

### Siguiente paso

Revisar este informe y, cuando esté listo, aplicar el feedback a requirements/design/tasks; las aprobaciones se reinician para revisión humana antes de avanzar fases.
