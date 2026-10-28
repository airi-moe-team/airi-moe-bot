# Plan de implementación

- [x] 1. Añadir transporte streaming de diagnóstico sin cambiar el default
- [x] 1.1 Medir TTFT y ensamblar SSE respetando el contrato de respuesta actual
  - Permitir que el benchmark solicite streaming y mantener no-streaming como default de todos los callers.
  - Leer eventos SSE incrementalmente aunque los fragmentos de red corten líneas o JSON.
  - Medir tiempo desde el POST hasta el primer delta generado y hasta el primer delta de contenido visible.
  - Ensamblar solo `content` para el parser JSON normal; no mezclar reasoning en la respuesta.
  - _Requirements: 1.1, 1.2, 1.4, 4.2, 6.1, 6.2_

- [x] 1.2 Conservar timings y metadatos de razonamiento explícitos
  - Extraer usage, finish reason y timings numéricos internos cuando el backend los envíe.
  - Registrar presencia de `reasoning_content` y tokens de reasoning solo ante un conteo explícito.
  - Dejar campos no entregados por el servidor en null y no estimarlos desde texto/caracteres.
  - No registrar ni serializar texto de reasoning.
  - _Requirements: 1.2, 1.3, 2.1, 2.2, 6.2, 6.3_

- [x] 2. Propagar timings opt-in al benchmark preservando Airi normal
- [x] 2.1 Transportar selector de streaming y metadata a través del turno
  - Habilitar streaming exclusivamente desde el contexto benchmark y conservar el comportamiento normal no-streaming.
  - Añadir timings opcionales y forward-compatible al resultado temporal de la inferencia.
  - Verificar que mensaje, historial, schema, parámetros, límite, thinking y variante de prompt permanecen constantes.
  - _Requirements: 1.4, 2.1, 2.3, 4.1, 4.2, 6.1, 6.4_

- [x] 2.2 Tratar correctamente fallos y formatos incompatibles
  - Marcar como fallida una muestra cuando HTTP/SSE no sea compatible, sin reintentar silenciosamente en no-streaming.
  - Continuar con las muestras independientes siguientes y no guardar texto de excepciones.
  - Representar TTFT, contenido inicial, usage y timings no disponibles sin inferir valores.
  - _Requirements: 1.3, 2.2, 4.3, 5.2_

- [x] 3. Incorporar snapshots opcionales de Prometheus
- [x] 3.1 Consultar métricas de solo lectura antes y después de cada muestra
  - Aceptar un endpoint de métricas opcional y hacer únicamente GET con timeout acotado.
  - Parsear métricas numéricas y comparar series solo cuando nombre y labels coincidan.
  - Detectar reinicio/reset de counters, métricas ausentes y errores HTTP como estados explícitos.
  - No iniciar, detener, reiniciar ni modificar llama-server.
  - _Requirements: 3.1, 3.3, 3.4, 5.2_

- [x] 3.2 Etiquetar el alcance de los deltas del servidor
  - Asociar snapshots al índice de muestra sin presentarlos como per-request si el endpoint no ofrece correlación.
  - Reportar tipo/labels/delta y el alcance agregado, evitando añadir bodies arbitrarios de métricas.
  - Continuar el benchmark si Prometheus no está configurado o no responde.
  - _Requirements: 3.2, 3.3, 5.1_

- [x] 4. Integrar reporte, CLI y pruebas de extremo a extremo
- [x] 4.1 Ampliar el reporte privado con métricas streaming y servidor
  - Mostrar TTFT y primer content por separado junto a latencia total, usage, finish reason y timings internos disponibles.
  - Incluir presencia/recuento de reasoning solo si el servidor lo reporta explícitamente.
  - Añadir deltas Prometheus con etiqueta clara de métrica agregada y campos ausentes como null.
  - Garantizar que el reporte no incluya mensajes, historial, prompt, content ni reasoning.
  - _Requirements: 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 5.1, 5.2, 6.2_

- [x] 4.2 Hacer visible la configuración requerida sin administrar el servidor
  - Añadir al CLI indicaciones de `--perf` para timings internos y `--metrics` para el endpoint Prometheus.
  - Advertir que `--expert-stats` no es un medidor temporal y que las flags dependen del `--help` del build local.
  - Mantener la guía en modo informativo; no ejecutar comandos de ciclo de vida sobre llama-server.
  - _Requirements: 3.4, 5.3, 5.4_

- [x] 4.3 Verificar compatibilidad con tests y fakes
  - Probar TTFT en primer delta, TTFT antes del contenido visible y stream con fragmentación arbitraria.
  - Probar que las peticiones habituales siguen no-streaming y que benchmark no altera parámetros A/B.
  - Probar usage/timings/reasoning ausentes, SSE inválido, timeout, fallo de Prometheus y counter reset.
  - Probar que el reporte agregado queda libre de texto privado y que Prometheus se etiqueta como agregado.
  - _Requirements: 1.1, 1.3, 1.4, 2.2, 3.1, 3.2, 3.3, 4.1, 4.3, 5.1, 5.2, 6.3_

- [x] 5. Registrar metadatos por llamada y atribuir las reparaciones
- [x] 5.1 Centralizar la invocación al modelo con propósito explícito
  - Añadir un helper único que ejecute la llamada, aplique el reintento de `json_schema` a `json_object` y registre propósito, estado, duración, `finish_reason`, `usage`, timings y deltas.
  - Etiquetar los seis puntos de invocación de `_generate` sin cambiar el comportamiento de reparación.
  - Mantener `llm_finish_reason` como agregado y conservar el de la primera llamada en `llm_calls[0]`.
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 5.2 Solicitar `usage` en streaming sin alterar la ruta normal
  - Enviar `stream_options: {include_usage: true}` solo con streaming y solo en perfiles que lo soportan.
  - Contar deltas por canal como proxy etiquetado, sin presentarlos como tokens exactos.
  - Dejar la ruta no-streaming de producción sin cambios.
  - _Requirements: 7.4, 1.4_

- [x] 5.3 Exponer la atribución en el reporte del benchmark
  - Añadir `call_count`, `repair_ms`, `primary_finish_reason`, `call_purposes` y `calls` a cada muestra.
  - Agregar `call_purposes` al reporte y mantener nulos los campos en trazas históricas.
  - Copiar solo campos de una lista blanca para que ningún texto llegue al JSON.
  - _Requirements: 7.5, 7.6, 7.3_

- [x] 5.4 Hacer auditable la neutralización de thinking
  - Registrar `thinking_requested_off` y `thinking_effective` por llamada.
  - Cubrir con pruebas el caso `LLM_THINKING_MODE=on` en un turno rápido.
  - _Requirements: 7.7_

- [x] 5.5 Verificar con pruebas
  - Turno normal con una llamada, truncamiento con dos y reparación por vacío con su propósito.
  - Conteo de deltas, solicitud de `usage` por perfil y ausencia de conteos en no-streaming.
  - Reporte con `call_purposes` agregados y sin texto privado.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 6. Permitir override per-call de thinking solo para reparaciones
- [x] 6.1 Separar política global y override de reparación
  - Mantener la política global actual para cada llamada primaria.
  - Añadir un override explícito por llamada para reparaciones de truncamiento, respuesta vacía, repetición, cierre interrogativo y coherencia.
  - Asegurar que el override bajo `LLM_THINKING_MODE=on` envíe `enable_thinking=false` solo para la reparación; no modificar variables de entorno ni configuración del servidor.
  - Registrar `thinking_effective` desde el payload realmente enviado.
  - _Requirements: 7.8, 7.9_

- [x] 6.2 Cubrir los modos y caminos de reparación con TDD
  - Probar llamadas primarias y reparaciones con modos globales `on`, `auto` y `off`.
  - Cubrir streaming/no-streaming y fallback de `json_schema` a `json_object`.
  - Verificar que todas las clases de reparación aplican el override y que sus metadatos coinciden con el payload.
  - Garantizar que no se registran prompts, mensajes, content ni reasoning.
  - _Requirements: 7.8, 7.9_

- [x] 6.3 Ejecutar regresión completa
  - Ejecutar pruebas unitarias e integración y comprobar que la llamada primaria y la respuesta normal no cambian.
  - _Requirements: 7.8, 7.9_
