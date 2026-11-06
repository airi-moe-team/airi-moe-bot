# Plan de implementación

- [x] 1. Definir el contrato de captura y su activación opt-in
- [x] 1.1 Modelar el contexto de llamada y su estado de captura
  - Escribir pruebas primero para contexto correlacionado por turno, propósito e índice de llamada.
  - Cubrir estado de captura ausente, capturado, no soportado y fallido.
  - Mantener compatibles clientes LLM y fakes que no usan captura.
  - Verificar que el contexto de captura no se incorpora a los mensajes enviados al modelo.
  - _Requirements: 1.3, 1.4, 4.1_

- [x] 1.2 Configurar captura apagada por defecto
  - Probar que configuración vacía no construye ni inyecta un capturador.
  - Probar que una ruta configurada habilita captura solo para la ejecución local de Airi.
  - Mantener sin cambios llamadas, payload HTTP y trazas cuando la captura está desactivada.
  - _Requirements: 1.1, 3.1_

- [x] 2. Guardar el payload efectivo en sidecars locales
- [x] 2.1 Implementar escritura y asociación del artefacto
  - Escribir primero pruebas de round-trip que comparen el payload guardado con el objeto JSON de entrada.
  - Guardar el cuerpo completo y metadatos de esquema, correlation ID, propósito e índice de llamada.
  - Calcular checksum SHA-256 sobre los bytes persistidos y generar referencia relativa estable.
  - Escribir de forma atómica y evitar colisiones o reemplazos accidentales.
  - Excluir URL, cabeceras, credenciales y secretos de configuración del sidecar.
  - _Requirements: 1.2, 2.1, 2.3, 3.2, 3.3_

- [x] 2.2 Validar referencias al cargar un sidecar
  - Probar referencia correcta, archivo ausente, JSON ilegible y checksum incorrecto.
  - Rechazar identificador de turno o llamada que no coincida con los metadatos del sidecar.
  - Informar errores sin incluir contenido del payload en excepciones ni logs.
  - _Requirements: 2.4, 2.5_

- [x] 3. Capturar el cuerpo que realmente se envía al backend
- [x] 3.1 Integrar captura antes de la petición HTTP
  - Probar primero que el JSON del sidecar coincide exactamente con el argumento enviado al POST.
  - Capturar después de aplicar modelo, parámetros, formato, tools y extensiones del proveedor.
  - Usar el mismo punto de captura para streaming y no-streaming.
  - No mutar el payload de inferencia al serializar la captura.
  - _Requirements: 1.2, 1.4, 4.1, 4.4_

- [x] 3.2 Mantener inferencia ante fallos de captura o HTTP
  - Probar fallo de serialización/escritura y verificar que la petición sigue al backend.
  - Guardar el estado de captura en el contexto antes de iniciar la petición.
  - Verificar que un fallo HTTP posterior conserva la referencia del request que sí se capturó.
  - Asegurar que mensajes de error y logs no revelan payload ni contenido sensible.
  - _Requirements: 2.1, 3.4, 3.5_

- [x] 4. Vincular cada sidecar con la traza y proteger la compatibilidad
- [x] 4.1 Registrar metadatos por invocación del modelo
  - Probar asociación independiente para llamada primary, review, reparación y reintento.
  - Añadir a cada entrada de llamada estado, referencia relativa y checksum, sin incluir el body.
  - Cubrir tanto respuestas correctas como errores del backend después del envío.
  - _Requirements: 1.3, 2.2, 4.2_

- [x] 4.2 Mantener trazas y replay históricos
  - Probar lectura de trazas sin metadatos `payload_capture`.
  - Verificar que replay determinista antiguo sigue produciendo el resultado anterior.
  - Informar payload no disponible o captura inválida sin convertirlo en divergencia del turno.
  - _Requirements: 2.5, 4.3_

- [x] 5. Verificar integración de extremo a extremo
- [x] 5.1 Probar configuración, request, sidecar y traza juntos
  - Construir un caso sintético con varias llamadas al LLM y captura habilitada.
  - Verificar que traza y sidecars se enlazan por turno, propósito e índice.
  - Probar modo streaming, fallo HTTP y fallo local de escritura sin alterar el flujo conversacional.
  - Verificar ausencia completa de sidecars con captura desactivada.
  - Ejecutar pruebas de adaptador HTTP, metadata de llamadas, serialización de trazas y replay.
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.5, 4.2, 4.3, 4.4_

- [x] 6. Capturar la response completa y mantener traza como índice
- [x] 6.1 Persistir la salida completa del LLM por llamada
  - Escribir primero pruebas que demuestren que `output.content` queda idéntico al string devuelto a Airi, sin recorte ni saneamiento.
  - Guardar en sidecar response identidad de llamada y metadata disponible, incluidas tool calls normalizadas.
  - Capturar salida ensamblada streaming y salida no-streaming sin persistir framing SSE.
  - Registrar `not_produced` cuando el backend falla después del request.
  - _Requirements: 2.1, 3.2, 5.1, 5.2, 5.3_

- [x] 6.2 Enlazar artefactos duales y omitir respuesta inline de trazas capturadas
  - Probar referencias/status/hash request y response en cada llamada y trace summary sin cuerpos completos.
  - Mantener `raw_llm` en memoria para parsing y resultado final.
  - Omitir `raw_llm` al serializar solo si la response artifact quedó capturada correctamente.
  - Mantener inline `raw_llm` como fallback si captura está apagada o la escritura response falla.
  - _Requirements: 2.2, 3.1, 4.1, 4.2, 5.2, 5.4_

- [x] 7. Preservar replay y migrar configuración de artefactos
- [x] 7.1 Hidratar respuesta desde sidecar en replay determinista
  - Escribir pruebas first para replay de traza nueva sin `raw_llm` usando response artifact validada, sin crear clientes/red.
  - Mantener fixtures históricas con `raw_llm` inline sin cambios.
  - Rechazar sidecar ausente, truncado o con identidad/hash inválido como no reproducible, no como divergencia.
  - _Requirements: 2.4, 2.5, 4.2, 4.3, 4.4_

- [x] 7.2 Renombrar la configuración y verificar flujo completo
  - Añadir `AIRI_TRACE_LLM_ARTIFACTS_DIR`/`TRACE_LLM_ARTIFACTS_DIR`; preservar aliases `*_PAYLOAD_DIR` durante transición.
  - Cambiar la ruta local de ejemplo a `private-llm-artifacts` y conservar captura off en `.env.example`.
  - Probar precedence, opt-in apagado y lectura de referencias existentes bajo el root configurado.
  - Ejecutar suite completa, replay histórico y validación de request/response pair end-to-end.
  - _Requirements: 3.1, 3.6, 4.2, 4.3, 5.2_

- [x] 8. Capturar razonamiento como dato privado separado
- [x] 8.1 Persistir reasoning_content en el response sidecar
  - Escribir primero pruebas para salida no-streaming con reasoning_content y ausencia cuando el proveedor no lo incluye.
  - En streaming, ensamblar los deltas de razonamiento en orden y guardarlos separados de content.
  - Mantener ambos campos íntegros en el response artifact sin incluir framing SSE.
  - _Requirements: 6.1, 6.2, 6.5_

- [x] 8.2 Mantener razonamiento fuera de trazas y replay
  - Verificar que la traza contiene solo referencia/hash y nunca el texto de razonamiento.
  - Verificar que replay hidrata solo content y que su resultado determinista no depende de reasoning_content.
  - _Requirements: 6.3, 6.4_
