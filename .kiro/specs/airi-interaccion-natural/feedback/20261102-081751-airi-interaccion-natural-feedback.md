# Feedback de desarrollo — airi-interaccion-natural

- **Items:** 1
- **Severidad:** 1 major
- **Aprobaciones a reiniciar:** requirements, design y tasks.
- **Responsable:** implementación del agente; revisión final por la persona usuaria.

## FB-DIARY-PRIVACY-SCOPE — Aislar el diario por interlocutor y reducir duplicados

**Contexto e impacto:** `!diario` mostraba entradas de todo el servidor pese a que cada una tiene `user_id`. Además, autodescubrimientos se guardaban en `self_notes` y otra vez como evento `discovery`; las reflexiones del modelo estaban supeditadas al level-up.

**Dirección aprobada:**

- En público, cada persona ve solo entradas de diario asociadas a su propio `user_id`.
- El dueño puede solicitar la vista completa mediante `!diario todos` por DM; el comando nunca publicará esa vista en un canal.
- Presentar claramente eventos automáticos frente a reflexiones de Airi.
- Mantener autodescubrimientos en `self_notes` sin copiarlos como eventos duplicados del diario.
- Guardar reflexiones emocionales/significativas aunque no suba la afinidad, conservando el límite, deduplicación y exclusión proactiva.
