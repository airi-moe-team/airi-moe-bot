# Feedback de desarrollo — airi-interaccion-natural

- **Items:** 1
- **Severidad:** 1 minor
- **Aprobaciones a reiniciar:** ninguna; la persona usuaria aprobó expresamente estos cambios para implementación.
- **Responsable:** agente de implementación; revisión final por la persona usuaria.

## FB-TRAITS-MORE-VISIBLE — Hacer más perceptible la evolución de traits

**Contexto e impacto:** Los rasgos apenas cambian de forma visible porque el prompt pide justificación genuina y los límites predeterminados son conservadores. Además, la presentación muestra los traits individuales como números, sin facilitar la comparación visual.

**Dirección aprobada:**

- Mostrar barras 1–5 en dimensiones generales: Expresividad, Humor, Curiosidad y Reactividad, sin alterar los traits canónicos.
- Admitir evidencia conversacional repetida o experiencias claras para cambios graduales; no exigir sucesos extraordinarios ni inventar motivos.
- Un descubrimiento sobre un patrón estable dispara la evaluación del trait relacionado, pero no es evidencia suficiente por sí solo. Si cambia un trait en la misma reflexión, se enlaza con `discovery_ref`.
- El prompt clasifica cada nota con `Patrón estable:`, `Contextual:` o `Hipótesis:`; evita nombres de usuarios, mezcla de personas y causas psicológicas especulativas presentadas como hechos.
- Defaults: 900 segundos entre cambios globales, 2 cambios por clave cada 24 horas y decaimiento hacia baseline cada 30 días.
- Mantener los requisitos de evidencia, allowlist y límites de intensidad.

**Checkpoint:** implementación completada con tests focalizados; suite completa mantiene fallos preexistentes en áreas ajenas a traits.
