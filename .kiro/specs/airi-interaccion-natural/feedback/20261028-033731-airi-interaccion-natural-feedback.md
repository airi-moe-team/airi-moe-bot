# Feedback SDD — airi-interaccion-natural

- **Elementos:** 1
- **Severidad:** 1 major
- **Aprobaciones a restablecer:** requirements, design y tasks, porque se modifican los tres documentos.
- **Responsable:** desarrollo; revisión y aprobación de documentos por la persona usuaria antes de implementar.
- **Próximo punto de revisión:** después de aplicar el feedback y antes de avanzar a implementación.

## FB-PERSONALITY-TRAITS — Eliminar la doble fuente entre personalidad fija y traits mutables

**Contexto e impacto:** `SYSTEM_PROMPT` y `SYSTEM_PROMPT_COMPACT_CANDIDATE` fijan cualidades de personalidad que pueden contradecir los valores numéricos mutables inyectados desde `self_model`. `PERSONALITY_TENDENCIES_PROMPT` también repite cualitativamente los rasgos. Esto obliga al modelo a reconciliar dos fuentes y puede neutralizar la evolución de los traits.

**Recomendación:** mantener en el prompt base la identidad estable y las reglas universales; usar los valores actuales 1–5 como única fuente de intensidad para expresividad, timidez, juego, celos, sarcasmo y curiosidad. Conservar los matices conductuales, condicionados por los valores de traits y el contexto. Aplicar la misma regla a ambas variantes y actualizar las pruebas para que comprueben la separación, no la presencia de etiquetas fijas.

**Cambios propuestos:**

- **Requirements:** identidad estable separada; intensidad derivada de traits actuales; guía cualitativa contextual, no duplicada; misma precedencia en `compact_candidate`; tests desacoplados del texto fijo.
- **Design:** retirar definiciones estáticas solapadas, conservar reglas no variables y asegurar que `render_self_section` aporte los valores actuales.
- **Tasks:** escribir primero pruebas de regresión; refactorizar ambas variantes y la guía cualitativa; ejecutar las pruebas unitarias pertinentes y la suite aplicable.

**Pregunta para la revisión:** confirmar que los seis traits son la única fuente de intensidad para esos rasgos y que se conserva como estable la identidad narrativa no relacionada con ellos.
