# Requirements Document

## Introducción

La extensión añade observabilidad temporal a las corridas live del benchmark de system prompt. Debe medir el TTFT desde el cliente, recuperar timings de prompt-eval/generación cuando llama-server los entregue y, opcionalmente, tomar snapshots del endpoint Prometheus. Esto permitirá distinguir espera inicial, prefill, decodificación y variación del servidor sin alterar la inferencia normal de Airi ni guardar contenido privado.

## Requisitos

### Requisito 1: TTFT medido desde el cliente
**Objetivo:** Como responsable del benchmark, quiero conocer cuánto tarda en llegar el primer token generado, para separar latencia inicial de decodificación.

#### Criterios de aceptación
1. WHEN una muestra benchmark usa streaming THEN el cliente SHALL medir con reloj monotónico desde antes del envío HTTP hasta el primer fragmento que contenga texto generado, omitiendo eventos de rol/metadatos vacíos.
2. WHEN la respuesta finaliza THEN el cliente SHALL registrar TTFT, latencia total, `finish_reason` y campos de `usage` que el servidor haya enviado.
3. IF el servidor o el formato de streaming no expone un primer fragmento medible THEN el benchmark SHALL marcar TTFT como no disponible y explicar el motivo, sin inferir un valor.
4. WHEN se ejecuta una conversación normal de Airi THEN el cliente SHALL conservar el modo no-streaming y su comportamiento actual por defecto.

### Requisito 2: Timings internos del servidor
**Objetivo:** Como responsable del benchmark, quiero registrar timings internos de prompt-eval y generación cuando estén disponibles, para comparar fases del coste de inferencia.

#### Criterios de aceptación
1. WHEN la respuesta o telemetría de llama-server incluye timings internos THEN el benchmark SHALL conservar por separado duración de evaluación del prompt y generación, sus tokens y tasas de tokens/segundo cuando existan.
2. IF la versión del servidor no entrega alguno de esos campos THEN el reporte SHALL dejarlo nulo/no disponible y SHALL continuar con las demás métricas.
3. WHEN se presenta el análisis THEN el reporte SHALL distinguir claramente tiempos del cliente (TTFT/total), timings internos del servidor y diferencias entre ambos.

### Requisito 3: Métricas Prometheus opcionales
**Objetivo:** Como responsable del benchmark, quiero correlacionar snapshots de `/metrics` con las muestras, para detectar carga o variación acumulada del servidor.

#### Criterios de aceptación
1. IF se configura un endpoint Prometheus de llama-server THEN el runner SHALL tomar snapshots antes y después de la muestra o bloque benchmark y registrar los deltas de contadores compatibles.
2. WHEN una métrica del endpoint no es por-request o no tiene correlación inequívoca THEN el reporte SHALL etiquetar el delta como agregado/no atribuible estrictamente a una sola inferencia.
3. IF el endpoint no está configurado o no responde THEN el benchmark SHALL seguir con TTFT y timings disponibles, reportando las métricas Prometheus como ausentes sin fallar toda la medición.
4. WHEN el runner consulta telemetría THEN SHALL usar solicitudes HTTP de lectura solamente y no SHALL iniciar, detener, reiniciar ni reconfigurar el proceso llama-server.

### Requisito 4: Comparación experimental controlada
**Objetivo:** Como responsable del experimento, quiero mantener iguales las condiciones de los brazos A/B, para que las mediciones nuevas sigan aislando la variante del system prompt.

#### Criterios de aceptación
1. WHEN se comparan prompts THEN el runner SHALL mantener iguales modelo, mensajes, historial, estado inicial, schema, topes, sampling y thinking efectivo.
2. WHEN se habilita streaming o Prometheus THEN esas opciones SHALL limitarse al benchmark y SHALL no cambiar la semántica del contenido solicitado ni los parámetros de generación.
3. WHEN una muestra no puede ejecutarse por incompatibilidad de streaming THEN el benchmark SHALL informar el fallo explícitamente y SHALL no sustituir silenciosamente esa muestra por no-streaming.

### Requisito 5: Privacidad y trazabilidad
**Objetivo:** Como responsable del proyecto, quiero conservar métricas útiles sin exponer conversaciones, para repetir y compartir el análisis de forma segura.

#### Criterios de aceptación
1. WHEN se muestra o guarda un reporte THEN SHALL incluir ID de traza, variante, pareja/muestra, hash del prompt y métricas temporales, pero SHALL excluir mensajes, historial, prompt completo y respuesta.
2. WHEN faltan datos o falla una muestra THEN el reporte SHALL registrar el tipo de fallo y campos ausentes sin incluir texto de excepción que pudiera ecoar contenido privado.
3. WHEN se informa configuración recomendada del servidor THEN SHALL indicar que `--perf` activa timings internos y `--metrics` habilita endpoint Prometheus, y SHALL advertir que `--expert-stats` no reemplaza mediciones temporales.
4. IF una opción no aparece en la ayuda del binario local THEN la guía SHALL marcarla como dependiente de versión/build y SHALL pedir validación mediante `llama-server --help` antes de usarla.

### Requisito 6: Compatibilidad de razonamiento
**Objetivo:** Como responsable del experimento, quiero preservar thinking on y el manejo normal de Airi, para no confundir cambios de transporte/medición con cambios de razonamiento.

#### Criterios de aceptación
1. WHILE se ejecuta el benchmark THE sistema SHALL exigir y verificar thinking efectivo activado.
2. WHEN se habilita un formato separado de reasoning (por ejemplo `reasoning_content`) THEN el benchmark SHALL marcar por separado su disponibilidad y no SHALL confundirlo con `content` visible.
3. IF el cliente de Airi no interpreta el campo separado de reasoning THEN SHALL mantener intacta la respuesta visible actual y SHALL reportar el campo como no consumido, sin cambiar el parseo de producción.
4. WHEN se implementa esta extensión THEN SHALL NOT modificar el presupuesto de razonamiento ni activar/desactivar thinking como parte de la comparación.

### Requisito 7: Atribución por llamada
**Objetivo:** Como responsable del benchmark, quiero saber cuántas inferencias hubo en un turno, por qué y cuánto duró cada una, para separar la respuesta visible del coste de las reparaciones.

#### Criterios de aceptación
1. WHEN un turno invoca al modelo THEN la traza SHALL registrar una entrada por invocación con propósito (principal, reintento de esquema estricto, reparación de truncamiento, de cierre, de vacío, de repetición o de coherencia), estado, duración, `finish_reason`, `usage` y timings disponibles.
2. WHEN una reparación reemplaza la respuesta THEN la traza SHALL conservar el `finish_reason` real de la primera llamada además del agregado actual, sin sobrescribir ninguno de los dos.
3. WHEN se registra una llamada THEN SHALL NOT incluir prompt, mensajes, historial, `content` ni reasoning; solo metadatos numéricos y de estado.
4. WHEN el transporte es streaming THEN el cliente SHALL solicitar `usage` al servidor cuando el perfil lo soporte y SHALL registrar deltas por canal como proxy, sin presentarlos como conteo exacto de tokens de razonamiento.
5. WHEN la traza es histórica y no tiene metadatos por llamada THEN el reporte SHALL dejar los campos nuevos en `null` sin fallar.
6. WHEN se construye el reporte THEN `ttft_ms` y `server_timings` SHALL describir la primera llamada, `llm_ms` el turno completo y `repair_ms` la suma de las llamadas posteriores.
7. WHEN el modo global de thinking pisa lo pedido por una reparación THEN el registro SHALL exponer ambos valores para que la diferencia sea auditable.
8. WHEN una reparación por truncamiento, respuesta vacía, repetición, cierre interrogativo o coherencia solicita desactivar thinking THEN el adaptador SHALL permitir el override por llamada aunque `LLM_THINKING_MODE=on`, sin modificar la política de thinking de la llamada primaria.
9. WHEN se aplica el override THEN los metadatos por llamada SHALL registrar el valor solicitado y el efectivo, y las pruebas SHALL verificar que la llamada primaria conserva la política global.
