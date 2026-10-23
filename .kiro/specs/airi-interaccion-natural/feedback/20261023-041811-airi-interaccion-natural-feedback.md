# Informe de feedback: `airi-interaccion-natural`

**Fecha:** 2026-10-23 04:18 UTC  
**Elementos:** 5 (5 major)  
**Documento objetivo:** `requirements.md`  
**Aprobaciones a restablecer:** requisitos (todavía no aprobados); diseño y tareas no existen.

## FB-001 — Acotar el primer incremento a escucha pasiva e intervención espontánea

**Impacto:** El alcance actual incluye buffer, disparadores, retirada, mediación y retorno; no refleja la decisión de empezar con el modo espectador.

**Actualización recomendada:** Empezar por buffer pasivo y disparadores locales. Posponer hostilidad, mediación/DM, retorno, inactividad y picos de actividad.

## FB-002 — Tratar interés y afinidad como disparadores independientes

**Impacto:** La regla AND exigiría dos señales a la vez, contrario a la decisión acordada.

**Actualización recomendada:** Mención/reply activa siempre; un tema de interés **o** afinidad sobre el umbral puede activar por separado.

## FB-003 — Usar el perfil de gustos existente como fuente canónica

**Impacto:** Un catálogo duplicado puede divergir de la personalidad de Airi.

**Actualización recomendada:** El detector local consulta los gustos positivos del perfil/self-model existente. No duplica la lista; aliases y normalización se detallarán en diseño.

## FB-004 — Separar la causa local del despertar del contexto enviado al LLM

**Impacto:** Inyectar al prompt el umbral o la regla exacta podría hacer que la respuesta suene mecánica.

**Actualización recomendada:** El evaluador decide localmente si despierta. El LLM recibe el contexto reciente con atribución de autores y el prompt habitual de Airi, sin una etiqueta del motivo de activación. Evitar mensajes duplicados y no forzar una pregunta al final.

## FB-005 — Definir límites de frecuencia y pruebas deterministas

**Impacto:** Una persona con afinidad alta podría provocar respuestas repetidas; sin límites no se garantiza el modo espectador.

**Actualización recomendada:** Añadir cooldown, buffer con límite/TTL y tests para silencio, interés por sí solo, afinidad por sí sola, mención y repetición durante cooldown. Inyectar azar solo si se decide que haya probabilidades.

## Pregunta para la fase de diseño

Definir cómo se normalizan temas y alias (por ejemplo, «ramen» y «ramen japonés») y cuál es el nivel de afinidad que habilita el disparador. La respuesta de Airi debe seguir siendo natural: puede reaccionar sin preguntar obligatoriamente.

**Responsable:** usuario y agente, mediante revisión de requisitos.  
**Siguiente paso:** integrar estas actualizaciones en `requirements.md` y revisar/aprobar el resultado antes de generar diseño.
