# Feedback: override de thinking en reparaciones

- **Feature:** `observabilidad-ttft-llama-server`
- **Feedback:** 1 elemento major
- **Aprobaciones que deberán reiniciarse:** requirements, design y tasks
- **Propietario:** implementador/mantenedor de Airi; el usuario revisa y aprueba los documentos

## FB-001 · Permitir que las reparaciones desactiven thinking realmente

**Contexto y evidencia:** E3 completó seis pares. La traza de llamadas muestra que las reparaciones piden apagar thinking (`thinking_requested_off=true`), pero el modo global `LLM_THINKING_MODE=on` lo deja activo (`thinking_effective=true`). Una reparación por truncamiento duró 81,5 s; varias reparaciones compactas llegaron a consumir hasta 149 s. El proceso de recuperación vuelve a pagar el coste de razonamiento que pretendía evitar.

**Actualización recomendada:** añadir un override explícito y acotado a llamadas de reparación. La llamada primaria debe seguir obedeciendo el modo global. El campo solicitado/efectivo debe mantenerse para auditar la política.

**Cobertura requerida:** modos globales `on`, `auto` y `off`; llamada primaria frente a reparaciones; streaming y no-streaming; truncamiento y regeneraciones; fallback de `json_schema` a `json_object`; privacidad de metadatos. No cambiar prompts, presupuesto global ni parámetros del servidor.

**Criterio de seguridad:** no modificar el comportamiento de la llamada primaria. En `LLM_THINKING_MODE=on`, solo las reparaciones marcadas deben poder enviar `enable_thinking=false`.

## Punto a confirmar

La recomendación extiende el override a todas las reparaciones clasificadas (truncamiento, respuesta vacía, repetición, cierre interrogativo y coherencia). Si se quiere limitarlo solo a truncamientos, ajustar el requisito antes de aplicar el feedback.

## Siguiente paso

Revisar el alcance de FB-001. Tras confirmación humana, aplicar el feedback a requirements/design/tasks; después revisar y aprobar esos documentos antes de ejecutar `spec-impl` con TDD.
