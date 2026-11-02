# Feedback — airi-conversacion-activa-llm

- **Elementos:** 1 (1 major)
- **Aprobaciones a reiniciar al aplicar:** requirements, design y tasks.
- **Responsable propuesto:** responsable de Airi para actualizar la spec e implementar; usuario para revisar y aprobar los documentos.
- **Punto de revisión:** revisar los documentos actualizados antes de iniciar implementación.

## FB-001 — Conservar el objetivo activo a través de interrupciones y turnos

**Impacto:** El contexto puede conservar mensajes recientes pero perder la actividad acordada. En la traza 02699f283523, la palabra “Moantai” se interpretó como petición de significado y no como la siguiente frase de un juego de adivinar animes. Este patrón puede afectar tareas de varios pasos, correcciones y retomadas.

**Recomendación:** Añadir un marco temporal y compacto del objetivo explícito, sus restricciones, progreso/próximo paso y ciclo de vida. Compartirlo con generación y herramientas; actualizarlo al continuar, corregir, cambiar o terminar la tarea. No persistirlo como memoria permanente ni permitir que mensajes automáticos lo sustituyan. Si el objetivo ya no está claro, preguntar antes de asumir.

### Cambios propuestos

- **Requirements:** conservar objetivo, restricciones y progreso; reconocer correcciones/cambios/cierre; dar contexto a herramientas; aislarlo y no guardarlo como memoria duradera; aclarar si no puede recuperarse.
- **Design:** integrar estado efímero con la conversación activa existente; definir su ciclo de vida y cómo se trata contenido automático; usarlo en generación y búsqueda sin ampliar indiscriminadamente el historial; aislar canales/participantes.
- **Tasks:** auditar límites de contexto, definir el contrato, integrarlo con generación y herramientas, probar actividades genéricas y validar privacidad, regresiones y coste.

**Siguiente paso:** aplicar este reporte a requirements/design/tasks; reiniciar sus aprobaciones y presentar los documentos para revisión humana antes de implementar.
