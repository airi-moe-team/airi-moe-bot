# Plan de implementación

- [x] 1. Establecer el contrato de modos y presupuestos
- [x] 1.1 Definir y probar los modos globales admitidos
  - Admitir `auto`, `low`, `medium` y `high`; los valores no admitidos recaen en `auto`.
  - Verificar normalización sin distinguir mayúsculas/minúsculas.
  - Verificar que `off` y otros valores desconocidos generan warning y fallback a `auto`.
  - Verificar que la configuración por defecto continúa siendo `auto`.
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 1.2 Formalizar los parámetros de presupuesto y turno rápido del cliente
  - Extender de forma consistente las llamadas con override opcional `reasoning_budget_tokens` y clasificación `quick_turn`.
  - Propagar los parámetros de `chat` a `chat_with_meta` y adaptar los fakes usados por servicios y pruebas.
  - Rechazar presupuestos negativos o inválidos antes de realizar la petición HTTP.
  - Mantener compatibilidad de contenido, schema, streaming y metadatos existentes.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 1.3 Resolver y emitir el presupuesto por modo y proveedor
  - Probar la precedencia del override local frente al modo y propósito global.
  - Mapear `low=256`, `medium=1024`, `high=4096`; mantener reasoning activo en cada modo.
  - En `auto`, usar medium en turno rápido y el presupuesto predeterminado en turno normal.
  - Para llama, enviar `chat_template_kwargs.enable_thinking=true` y el campo `thinking_budget_tokens` cuando aplique.
  - Verificar que los proveedores OpenAI y OpenAI-compatible no reciben extensiones propietarias.
  - Verificar que ninguna ruta envía `enable_thinking=false` ni cambia el modo global entre llamadas.
  - Verificar que `max_tokens` deja una reserva mínima de 512 tokens después del presupuesto de reasoning.
  - Si el backend activo está disponible, verificar el campo de presupuesto con una petición live no destructiva; no reiniciar/reconfigurar y registrar solo métricas no sensibles.
  - _Requirements: 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8, 5.4_

- [x] 2. Mantener reasoning activo en reparaciones e introspección
- [x] 2.1 Aplicar la resolución a llamadas de conversación
  - Mantener la señal `quick_turn` en la llamada primaria sin convertirla en un apagado global.
  - Asignar presupuesto medium a reparaciones de truncamiento, formato, cierre, respuesta vacía/repetida e incoherencia.
  - Comprobar que los overrides de reparación son locales y que la siguiente petición vuelve al modo global.
  - Actualizar regresiones de conversación y payloads de reparaciones, incluyendo date glue.
  - _Requirements: 1.4, 2.6, 3.2, 3.4, 6.1, 6.2_

- [x] 2.2 Mantener presupuesto bajo en reflexiones estructuradas
  - Asignar presupuesto low a llamadas introspectivas estructuradas de self_service.
  - Verificar que la llamada conserva reasoning y el override no cambia llamadas posteriores.
  - Verificar comportamiento seguro para proveedores distintos de `llama`.
  - _Requirements: 2.6, 2.8, 3.2_

- [x] 3. Registrar presupuesto solicitado y evidencia observada
- [x] 3.1 Extender metadatos y registro por llamada
  - Añadir un campo nullable para el presupuesto resuelto/enviado por el cliente.
  - Completarlo solo cuando el proveedor y la petición permitan determinar el valor enviado.
  - Registrar presupuesto junto a `reasoning_present` y `reasoning_tokens`, sin inferir que el backend lo obedeció.
  - Conservar metadatos de presupuesto en llamadas fallidas cuando ya se resolvió el payload.
  - Añadir pruebas de streaming y no streaming para la separación entre presupuesto enviado y evidencia recibida.
  - _Requirements: 4.1, 4.2, 4.4_

- [x] 3.2 Preservar las garantías de privacidad de las trazas
  - Verificar que llamadas registradas no contienen prompts, historial, contenido de respuesta ni reasoning.
  - Comprobar que los metadatos nuevos pasan por los eventos y reportes existentes sin filtrar contenido sensible.
  - _Requirements: 4.3_

- [x] 4. Adaptar benchmark y documentación a presupuestos
- [x] 4.1 Aceptar y validar los modos en el benchmark
  - Aceptar `auto`, `low`, `medium` y `high` cuando coincidan con el modo del cliente.
  - Rechazar valores inválidos o discrepancias con un error informativo.
  - Conservar el modo y presupuesto solicitado separados del uso observado.
  - _Requirements: 5.1, 5.2, 5.3_

- [x] 4.2 Integrar, documentar y verificar la migración de comportamiento
  - Actualizar configuración de ejemplo y documentación para eliminar el apagado, explicar presupuestos y anotar valores propuestos y alcance `llama`.
  - Ejecutar las pruebas unitarias e integración de adaptador, configuración, conversación, self_service, metadatos y benchmark.
  - Comprobar que ninguna llamada rápida, reparación o introspección envía apagado de reasoning.
  - Verificar que el default de `auto` mantiene reasoning en turnos rápidos y normales.
  - Evaluar calidad de presupuestos propuestos en cinco turnos reales antes de promoverlos como defaults.
  - _Requirements: 1.4, 1.5, 1.7, 2.1, 2.5, 2.6, 3.4, 5.4, 5.5, 6.1, 6.3, 6.4_

- [x] 5. Consolidar presets de razonamiento
- [x] 5.1 Retirar `on` y los overrides de entorno de los presets
  - Aceptar únicamente `auto`, `low`, `medium` y `high`; `on` debe advertir y caer a `auto`.
  - Agrupar los presupuestos fijos 256/1024/4096, fijar la reserva de 512 y asegurar que variables legacy no cambien los presets.
  - Actualizar pruebas, benchmark, `.env.example`, `.env` local y README.
  - Pruebas unitarias y de integración relacionadas ejecutadas correctamente.
  - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 5.1, 5.2_

- [x] 6. Agrupar límites de salida en perfil de generación
- [x] 6.1 Incorporar el perfil `balanced`
  - Agrupar topes general=8182 y breve=2048 en `LLM_GENERATION_PROFILE=balanced`, separado del modo de razonamiento.
  - Retirar los overrides de entorno `LLM_MAX_TOKENS` y `LLM_SHORT_MAX_TOKENS`, conservando overrides programáticos.
  - Mantener la selección del tope breve basada en `quick_turn` y la reserva de 512 tokens tras reasoning.
  - Actualizar pruebas, `.env`, `.env.example`, README y benchmark/configuración.
  - Ejecutar pruebas unitarias e integración relacionadas y Ruff.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 7. Elevar a medium el presupuesto de `auto` rápido y reparaciones
- [x] 7.1 Mantener intactos los modos explícitos y `self_service`
  - `auto` rápido y reparaciones/review usan 1024 tokens; `auto` normal mantiene el default del servidor.
  - Los modos explícitos low/medium/high conservan 256/1024/4096; `self_service` sigue usando low.
  - Actualizar pruebas, README, `.env.example` y validar la suite.
  - _Requirements: 1.5, 2.4, 2.6, 6.2_
