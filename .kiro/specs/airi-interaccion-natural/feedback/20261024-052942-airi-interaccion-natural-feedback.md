# Feedback Report — airi-interaccion-natural

**Generado:** 2026-10-24T05:29:42Z  
**Total items:** 1  
**Severidad:** major (1)

## Resumen
Se propone sembrar `last_human_activity` al arrancar usando el último mensaje humano válido del canal, para que la proactividad se base en la actividad real y no solo en lo ocurrido con el bot encendido.

## Aprobaciones a resetear
- requirements
- design
- tasks

## Detalle

### FB-008 — Sembrar last_human_activity al arrancar desde el último mensaje humano válido
- **Severidad:** major
- **Impacto:** La proactividad solo considera actividad ocurrida con el bot encendido; al reiniciar, `last_human_activity=None` y no se dispara hasta un mensaje nuevo.
- **Recomendación:** Implementar heurística reutilizable "último mensaje del canal sin respuesta" y, al arrancar, fetch del último mensaje humano válido para inicializar `last_human_activity` con su `created_at` (epoch).

**Actualizaciones propuestas:**
- **requirements:** al arrancar (si espectador habilitado) leer último mensaje del canal; si es humano válido inicializar `last_human_activity`; si no hay válido o falla, no bloquear arranque.
- **design:** corrutina aislada `seed_last_human_activity(client)`; sin cambios en `SpectatorSessionRegistry`; try/except; armar temporizador proactivo con delay 0 no bloqueante.
- **tasks:** implementar `_epoch`, `pending_user_message`, `seed_last_human_activity`, `arm_proactive_timer`, integración en `on_ready_extra`, pruebas.