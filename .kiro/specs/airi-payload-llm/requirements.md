# Requirements Document

## Introduction

Airi registra cada turno en una traza y permite depurar el request enviado al modelo. Para auditar una llamada completa, la captura opt-in guardará por separado el request efectivo y la respuesta completa que Airi recibe del LLM, enlazados desde la traza mediante identidad de llamada y checksums. Cuando ambos artefactos existan, la traza actuará como índice/resumen y no duplicará `raw_llm`; el resultado final visible y los metadatos del turno seguirán disponibles. Los artefactos se almacenan localmente y pueden alimentar replay determinista sin volver a llamar al modelo.

## Requirements

### Requirement 1: Captura opt-in del request HTTP efectivo
**Objective:** Como persona que depura una interacción, quiero conservar el JSON exacto que Airi envía al backend, para inspeccionar configuración y mensajes efectivos.

#### Acceptance Criteria
1. WHEN la captura está desactivada THEN el adaptador SHALL mantener el comportamiento actual y SHALL NOT crear artefactos de request ni referencias.
2. WHEN la captura está activada y el adaptador va a enviar una petición THEN SHALL guardar el cuerpo JSON efectivo después de aplicar modelo, parámetros, formato de respuesta y extensiones del proveedor.
3. WHEN un turno contiene más de una invocación al LLM THEN el sistema SHALL distinguir cada request por correlación, índice y propósito.
4. WHEN el transporte no usa un cuerpo JSON compatible THEN el sistema SHALL informar la limitación y SHALL NOT afirmar que la llamada es reproducible exactamente.

### Requirement 2: Artefactos locales enlazados y verificables
**Objective:** Como persona que audita una traza, quiero localizar y verificar los artefactos de request y response de cada llamada sin inflar el archivo principal.

#### Acceptance Criteria
1. WHEN el request o la response se capturan THEN el sistema SHALL guardar cada uno como artefacto local separado bajo un directorio configurable denominado para artefactos LLM.
2. WHEN la traza se serializa con artefactos disponibles THEN cada entrada de `llm_calls` SHALL incluir, por separado para request y response, estado, referencia relativa y SHA-256, junto con correlation ID, índice, propósito, modelo y proveedor; la traza SHALL NOT incluir el cuerpo completo de esos artefactos.
3. WHEN un artefacto se escribe THEN el sistema SHALL usar escritura atómica y SHALL evitar reemplazar accidentalmente otro artefacto.
4. WHEN se abre una referencia THEN el cargador SHALL verificar checksum, schema e identidad de turno/llamada antes de devolver el contenido.
5. IF falta un artefacto, no pasa validación o no coincide su checksum THEN el sistema SHALL reportarlo como no disponible/inválido sin filtrar contenido privado ni convertir por sí solo el hecho en una divergencia del comportamiento.

### Requirement 3: Captura íntegra local y apagada por defecto
**Objective:** Como responsable de la instancia local, quiero decidir explícitamente cuándo persistir llamadas completas, para conservar el comportamiento actual si no habilito la auditoría.

#### Acceptance Criteria
1. WHEN no se habilita explícitamente la captura THEN el sistema SHALL no crear sidecars y SHALL preservar el comportamiento actual de trazas.
2. WHEN se captura una llamada THEN el artefacto de request SHALL preservar íntegro el cuerpo JSON efectivo y el artefacto de response SHALL preservar íntegra la salida completa que el adaptador entrega a Airi antes del parsing, saneamiento o redacción de persistencia.
3. WHEN se guarda un artefacto THEN el sistema SHALL excluir URL, cabeceras HTTP, credenciales de autenticación y secretos de configuración, que no forman parte de la salida/request de aplicación capturado.
4. WHEN se informa un error de captura o carga THEN el sistema SHALL evitar imprimir contenido del request/response o secretos en logs y errores.
5. WHEN falla la escritura de un artefacto THEN el sistema SHALL continuar el flujo normal del turno y registrar el estado fallido sin crear referencias válidas falsas.
6. WHEN se configura el directorio THEN el sistema SHALL aceptar `AIRI_TRACE_LLM_ARTIFACTS_DIR` y el alias `TRACE_LLM_ARTIFACTS_DIR`; los nombres históricos `AIRI_TRACE_LLM_PAYLOAD_DIR` y `TRACE_LLM_PAYLOAD_DIR` SHALL seguir aceptándose como alias de compatibilidad.

### Requirement 4: Trazas resumidas y replay compatible
**Objective:** Como persona que investiga turnos, quiero que la traza resuma el resultado y enlace evidencia completa, para mantener una historia auditable sin duplicación.

#### Acceptance Criteria
1. WHEN el artefacto de response se captura correctamente THEN la traza serializada SHALL omitir el contenido completo de `raw_llm`, pero SHALL conservar `final_reply`, resultados del turno, metadatos de llamadas y referencia/hash de response.
2. WHEN una traza histórica contiene `raw_llm` inline THEN el lector y `airi-replay` SHALL seguir aceptándola sin modificación.
3. WHEN una traza nueva omite `raw_llm` porque tiene artefacto de response válido THEN `airi-replay` SHALL cargar esa response local como respuesta guardada y SHALL conservar el replay determinista sin invocar LLM ni red.
4. IF el artefacto response requerido por replay falta o es inválido THEN `airi-replay` SHALL informar claramente que la reproducción no está disponible y SHALL NOT inventar una respuesta.
5. WHEN la llamada usa streaming THEN el artefacto response SHALL preservar, en orden y sin pérdida, el contenido completo que el adaptador ensambla y devuelve a Airi; SHALL NOT necesitar persistir el framing SSE.

### Requirement 5: Aislamiento arquitectónico y correlación por llamada
**Objective:** Como mantenedor, quiero capturar en las fronteras existentes y enlazar cada pieza con una identidad estable, para preservar la arquitectura hexagonal.

#### Acceptance Criteria
1. WHEN se construye/envía el request THEN la captura SHALL ocurrir en el adaptador LLM; la captura de response SHALL ocurrir en el borde del adaptador antes de cualquier redacción de persistencia.
2. WHEN se registra una llamada THEN request, response y metadatos SHALL compartir correlation ID, índice y propósito, incluidos primary, review, reparaciones y retries.
3. WHEN falla el backend después de enviar el request THEN el artefacto request SHALL seguir enlazado y la response SHALL figurar como no producida/fallida, sin bloquear el error original.
4. WHEN se actualiza el esquema de referencias THEN trazas viejas con `payload_capture` o sin referencias SHALL continuar siendo legibles; la ruta nueva SHALL distinguir request y response.

### Requirement 6: Captura separada del texto de razonamiento
**Objective:** Como persona que depura una respuesta del modelo, quiero inspeccionar el razonamiento que el proveedor devuelve, separado del contenido visible y sin cambiar replay ni trazas.

#### Acceptance Criteria
1. WHEN el proveedor incluye texto de razonamiento THEN el response artifact SHALL preservarlo íntegramente en el campo opcional `reasoning_content`, separado de `content`, tanto en streaming como no-streaming.
2. WHEN el proveedor no devuelve razonamiento THEN el artefacto SHALL omitir `reasoning_content` o representarlo como ausente, sin inventar contenido.
3. WHEN se serializa la traza THEN SHALL NOT incluir texto de razonamiento; solo conservará la referencia y checksum del response artifact.
4. WHEN `airi-replay` hidrata una respuesta THEN SHALL usar solo `content`; `reasoning_content` no SHALL alterar el replay determinista.
5. WHEN la captura opt-in está desactivada THEN el sistema SHALL NOT almacenar texto de razonamiento.
