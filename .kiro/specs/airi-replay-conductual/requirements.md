# Requirements Document

## Project Description (Input)

Diseñar y agregar modos de replay conductual a Airi, preservando el replay determinista como opción predeterminada segura. El modo determinista debe indicar con claridad qué compara y qué queda sin verificar. Un modo conductual debe recorrer de nuevo la decisión de búsqueda y la síntesis usando datos capturados localmente (consulta/resultados), sin Internet ni servicios live; la captura de esos datos debe ser opt-in, con artefacto local, mientras las trazas normales no persisten consulta/resultados. Un modo live separado debe requerir opt-in explícito para inferencia real y una opción independiente para permitir búsqueda web real; nunca activar red implícitamente. Las sesiones con contexto privado de tarea deben aceptar fixtures laterales externos y registrar solo metadatos no sensibles en la traza por defecto. El reporte debe distinguir decisión de búsqueda, disponibilidad/resultado capturado, respuesta/grounding y continuidad de tarea, tratando datos ausentes como no verificables en vez de fallos. Incluir cobertura de la traza `traces/2026-11-02/1380da81d040.json` y fixtures sintéticos, controles de seguridad y privacidad, compatibilidad con trazas antiguas y documentación CLI.

## Introduction

`airi-replay` debe servir tanto para verificar una reproducción determinista como para investigar decisiones que dependen del LLM y de la búsqueda web. Hoy el replay reutiliza la respuesta cruda y desactiva la búsqueda, por lo que no puede reconstruir la decisión ni distinguir una búsqueda que no se pidió de una búsqueda que devolvió cero resultados. Esta feature añade modos explícitos y un informe que hace visibles sus límites, sin convertir la red ni la captura de datos privados en el comportamiento predeterminado.

## Requirements

### Requirement 1: Replay determinista seguro y honesto
**Objective:** Como persona que diagnostica una traza, quiero conservar un replay reproducible sin servicios externos y saber qué partes valida, para no confundir una limitación del replay con un fallo de Airi.

#### Acceptance Criteria
1. WHEN se ejecuta `airi-replay <traza>` sin opciones de modo THEN `airi-replay` SHALL usar el replay determinista existente, sin llamar al LLM, a búsqueda web ni a otros servicios externos.
2. WHEN el replay determinista termina THEN `airi-replay` SHALL informar por separado los checks comparados, los que fallaron y los aspectos no evaluados por falta de datos o por el modo elegido.
3. WHEN un dato externo no fue capturado en la traza THEN `airi-replay` SHALL marcar el check dependiente como «no verificable» y SHALL NOT tratar su ausencia como una divergencia de comportamiento de Airi.
4. WHEN `matches_original` se informa THEN `airi-replay` SHALL basarlo solo en checks aplicables y SHALL exponer además si la comparación fue completa o parcial.

### Requirement 2: Replay conductual con búsqueda capturada
**Objective:** Como persona que investiga una decisión web, quiero volver a ejecutar la decisión del LLM y la síntesis usando el resultado capturado, para probar el comportamiento sin repetir la búsqueda en Internet.

#### Acceptance Criteria
1. WHEN se solicita explícitamente el modo conductual y existe un artefacto de captura válido THEN `airi-replay` SHALL volver a ejecutar la inferencia con el LLM configurado y SHALL proporcionar un adaptador de búsqueda que responda exclusivamente con los datos capturados.
2. WHILE se ejecuta el modo conductual THE `airi-replay` SHALL NOT realizar solicitudes de red para búsqueda web.
3. WHEN el modelo solicita búsqueda THEN `airi-replay` SHALL usar el resultado capturado solo si corresponde a la consulta registrada según la política de coincidencia definida por el diseño; si no coincide, SHALL informar el resultado como no disponible en vez de reutilizar evidencia ajena.
4. WHEN el artefacto registra una búsqueda ejecutada sin resultados THEN `airi-replay` SHALL reproducir esa respuesta vacía como un resultado capturado válido, distinto de no haber buscado o de no disponer de captura.
5. WHEN falta el artefacto, está malformado o no contiene el dato necesario THEN `airi-replay` SHALL fallar de forma explicativa o marcar los checks afectados como no verificables, sin caer silenciosamente en búsqueda live.
6. WHEN se solicita el modo conductual THEN `airi-replay` SHALL indicar que se realizará inferencia con el backend LLM configurado antes de ejecutarla.

### Requirement 3: Captura local opcional de búsqueda
**Objective:** Como responsable de una traza, quiero decidir explícitamente si se guardan consulta y resultados web, para habilitar replay conductual sin aumentar la exposición de datos por defecto.

#### Acceptance Criteria
1. WHEN se registra un turno sin activar captura de replay THEN el sistema SHALL NOT persistir en la traza normal la consulta web ni el contenido crudo de resultados destinado al replay.
2. WHEN una persona activa explícitamente la captura y proporciona una ruta de salida THEN el sistema SHALL escribir un artefacto local separado que permita reproducir la decisión y el resultado web de ese turno.
3. WHEN se crea el artefacto de captura THEN el sistema SHALL incluir la consulta y los campos de resultado necesarios para el replay, y SHALL NOT incluir credenciales, tokens ni secretos de configuración.
4. WHEN la ruta de captura no se proporciona, no es escribible o apunta a un artefacto existente THEN el sistema SHALL informar el problema y SHALL NOT sobrescribir datos existentes sin una opción explícita de reemplazo.
5. WHEN una traza normal registra telemetría de búsqueda THEN el sistema SHALL limitarla a metadatos no sensibles suficientes para indicar si se decidió buscar, si la búsqueda se ejecutó y si hubo resultados, de acuerdo con la política de privacidad existente.

### Requirement 4: Replay live con permisos explícitos
**Objective:** Como persona que prueba una variante actual del comportamiento, quiero controlar de forma independiente el uso del LLM y el acceso web real, para evitar llamadas externas accidentales.

#### Acceptance Criteria
1. WHEN se solicita el modo live explícitamente THEN `airi-replay` SHALL volver a ejecutar la inferencia con el LLM configurado y SHALL NOT publicar en Discord ni persistir cambios en el estado de producción.
2. WHEN se solicita el modo live sin permiso explícito de búsqueda web THEN `airi-replay` SHALL mantener la búsqueda web deshabilitada.
3. WHEN se solicita acceso web live THEN `airi-replay` SHALL exigir también el modo live explícito y SHALL indicar antes de ejecutar que puede realizar solicitudes externas.
4. IF se combinan opciones de modo incompatibles THEN `airi-replay` SHALL rechazar la invocación con un mensaje que explique la combinación válida, sin ejecutar inferencia ni red.
5. WHEN falla el LLM o el proveedor web en modo live THEN `airi-replay` SHALL informar el fallo como error de ejecución y SHALL NOT presentarlo como resultado reproducido de la traza.

### Requirement 5: Fixture lateral para contexto privado de tarea
**Objective:** Como persona que prueba continuidad conversacional, quiero aportar el marco de tarea fuera de la traza, para reproducir ese contexto sin persistir su contenido sensible en la observabilidad normal.

#### Acceptance Criteria
1. WHEN se proporciona explícitamente un fixture de contexto de tarea THEN `airi-replay` SHALL validarlo y suministrarlo al turno reproducido como contexto de tarea.
2. WHEN no se proporciona el fixture de tarea THEN `airi-replay` SHALL marcar la continuidad de tarea como no evaluada, salvo que la traza contenga de forma segura los datos requeridos.
3. WHEN se serializa una traza normal THEN el sistema SHALL NOT incluir el contenido del fixture ni el texto del marco privado, y SHALL limitar cualquier metadato registrado a información no sensible, como presencia del fixture y versión del esquema.
4. WHEN el fixture está ausente, malformado o excede los límites admitidos THEN `airi-replay` SHALL emitir un error claro antes de usarlo y SHALL NOT incorporarlo parcialmente al prompt.

### Requirement 6: Informe diagnóstico por etapa
**Objective:** Como persona que corrige un fallo, quiero separar las etapas de decisión, búsqueda, grounding y respuesta, para identificar dónde se produjo la divergencia.

#### Acceptance Criteria
1. WHEN termina cualquier modo de replay THEN el informe SHALL distinguir como mínimo: decisión de buscar, disponibilidad del resultado, síntesis/respuesta, grounding y disponibilidad/evaluación del contexto de tarea.
2. WHEN la decisión de búsqueda no se vuelve a ejecutar en el modo seleccionado THEN el informe SHALL marcarla como no evaluada y SHALL NOT inferirla únicamente del resultado guardado.
3. WHEN el replay conductual reejecuta la decisión THEN el informe SHALL comparar si el modelo pidió búsqueda y la consulta con la captura, sin confundir una consulta distinta con una búsqueda sin resultados.
4. WHEN los checks tienen distintos niveles de cobertura THEN el resumen SHALL preservar resultados parciales por etapa en vez de reducirlos a un único booleano ambiguo.

### Requirement 7: Compatibilidad y cobertura de regresión
**Objective:** Como persona que mantiene Airi, quiero conservar la compatibilidad con trazas existentes y probar los casos límite de replay, para adoptar los modos nuevos sin invalidar regresiones históricas.

#### Acceptance Criteria
1. WHEN se reproduce una traza anterior que no contiene los campos nuevos THEN el replay determinista SHALL seguir funcionando con el comportamiento compatible y SHALL marcar como no verificables los datos que falten.
2. WHEN se prueba el caso `1380da81d040` con una captura que representa búsqueda ejecutada sin resultados THEN la prueba SHALL verificar que el modo conductual distingue correctamente búsqueda vacía, ausencia de búsqueda y ausencia de captura.
3. WHEN se prueban los modos nuevos THEN la suite SHALL cubrir fixtures sintéticos para búsqueda con resultados, búsqueda vacía, cambio de consulta, captura inválida, contexto de tarea presente/ausente, fallo del LLM y flags de red incompatibles.
4. WHEN se documenta la CLI THEN la documentación SHALL explicar modos, permisos de red, artefacto de captura, fixture de tarea, checks no verificables y ejemplos de uso seguros.
