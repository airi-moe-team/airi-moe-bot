# Feedback de desarrollo: airi-interaccion-natural

**Total:** 3 elementos — 3 major.  
**Aprobaciones a reiniciar:** requirements, design y tasks.  
**Responsables:** implementador para los cambios; usuario para revisar y aprobar los documentos actualizados.

## FB-018 — Añadir identidad narrativa breve de Airi (major)

**Impacto:** El prompt contiene reglas de actuación, pero no una premisa narrativa y preferencias concretas suficientes para sostener opiniones y reacciones individuales.

**Recomendación:** Añadir una identidad compacta que distinga premisa ficticia, identidad estable, experiencias confirmadas y roleplay. Evitar biografía recitable o recuerdos humanos inventados. No reintroducir la personalidad tsundere descartada previamente.

**Actualizaciones propuestas:**
- Requisitos: perspectiva estable basada en preferencias/valores; no recitar la historia cuando no venga al caso; separar identidad, experiencias compartidas y ficción.
- Diseño: bloque compacto compatible con honestidad, memoria y límites relacionales.
- Tareas: tests del bloque y evaluación de los seis escenarios con configuración idéntica entre baseline y candidato.

## FB-019 — Corregir concatenación y auditar contrato de salida (major)

**Impacto:** En `src/airi/domain/prompts.py` hay instrucciones concatenadas sin separación. `stay_active` pertenece al contrato de sesión, así que no debe declararse inválido sin verificar el modo/schema de la traza.

**Recomendación:** Corregir la separación y probarla; confirmar la traza y el esquema activo antes de tocar el contrato JSON.

**Actualizaciones propuestas:**
- Requisitos: mantener separación legible en el prompt y contrato acorde al modo.
- Diseño: conservar la distinción entre `RESPONSE_SCHEMA` y `SESSION_RESPONSE_SCHEMA`.
- Tareas: test de concatenación y test del contrato del modo de la traza.

## FB-020 — Separar evaluación de personalidad y latencia (major)

**Impacto:** Una identidad nueva no resolverá por sí sola el truncamiento a 4096 tokens ni la latencia elevada. Cambiar varias variables juntas impediría atribuir los resultados.

**Recomendación:** Comparar prompts con configuración fija; después medir thinking y límites de salida como experimento separado, sin cambiar producción automáticamente.

**Actualizaciones propuestas:**
- Requisitos: reportar por separado calidad narrativa y rendimiento.
- Diseño: experimento controlado posterior para thinking/presupuesto de salida; conservar reparación.
- Tareas: registrar `finish_reason`, tokens, latencia y reparaciones; probar perfiles alternativos de forma aislada.

## Pendiente de aprobación

La spec existente `airi-interaccion-natural` tiene las aprobaciones de requisitos, diseño y tareas sin marcar y `ready_for_implementation=false`. Por el flujo SDD, estos cambios deben integrarse en los documentos, revisarse y aprobarse antes de ejecutar implementación. La pregunta sobre `stay_active` queda abierta hasta identificar la traza y su modo.
