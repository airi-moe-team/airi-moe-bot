# Feedback SDD: transición a presupuestos de razonamiento

- Elementos: 1 (1 major)
- Documentos cuya aprobación se reinicia: requisitos, diseño y tareas.
- Responsable: implementación de la feature.

## FB-LLM-002 — Cambiar a presupuestos por nivel y mantener reasoning activo

**Decisión del usuario:** Los niveles serán presupuestos de razonamiento y el razonamiento nunca se apagará, tampoco en turnos rápidos.

**Propuesta para revisión:** `low=256`, `medium=1024`, `high=4096` tokens. `auto` razona siempre y usa presupuesto low en turnos rápidos; en turnos normales deja el presupuesto al servidor. `on` mantiene reasoning activo sin enviar límite por petición. Reparaciones e introspecciones estructuradas usan low.

**Integración:** llama.cpp ha usado `thinking_budget_tokens` como campo por petición, sujeto a que el build lo soporte y a que no se haya fijado `--reasoning-budget` al arrancar. No se verificó aún ese campo contra el servidor local. Confirmar versión/campo mediante petición live no destructiva; no reiniciar ni reconfigurar el servidor.

**Riesgo de calidad:** el presupuesto es un tope, no un nivel cognitivo. Un corte abrupto puede dejar menos espacio para la respuesta final; evaluar calidad en al menos cinco turnos reales antes de fijar/promover valores.
