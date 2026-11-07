# Requirements Document

## Introducción

Este experimento determina si una versión más compacta, organizada y coherente del system prompt de Airi mejora la latencia cuando el modelo opera con thinking activado, y distingue el coste de procesar el prompt del coste de generar la respuesta. La traza `traces/2026-10-26/722f84144006.json` proporciona el primer caso reproducible. La evaluación debe mantener la calidad conversacional y no atribuir causalidad a una única inferencia.

## Requisitos

### Requisito 1: Comparación controlada de prompts
**Objective:** Como responsable del experimento, quiero comparar el prompt actual con uno compacto y reorganizado, para aislar el efecto del system prompt bajo thinking activado.

#### Acceptance Criteria
1. WHEN se ejecuta una muestra de cualquiera de las variantes THEN el experimento SHALL usar el mismo modelo, configuración de generación, estado/contexto reconstruido y entrada de usuario para ambas variantes.
2. WHILE se ejecutan las muestras, EL experimento SHALL mantener thinking activado en todas las inferencias.
3. WHEN se cambia de variante THEN el experimento SHALL cambiar únicamente el contenido/organización del system prompt y no el historial, el contrato de salida, los límites de tokens ni otros parámetros.
4. WHERE se usa la traza de referencia, EL experimento SHALL cargar `traces/2026-10-26/722f84144006.json` sin publicar la respuesta ni persistir mutaciones del turno en Discord o en el estado de producción.

### Requisito 2: Compactación y coherencia del system prompt
**Objective:** Como responsable de Airi, quiero que la variante compacta elimine redundancias y aclare instrucciones que compiten entre sí, para reducir carga innecesaria sin degradar su comportamiento esencial.

#### Acceptance Criteria
1. WHEN se construye la variante compacta THEN el experimento SHALL conservar las reglas esenciales de identidad, prioridad de intención, honestidad, continuidad/memoria, límites relacionales y formato de salida.
2. WHEN dos o más reglas expresan la misma obligación THEN la variante compacta SHALL consolidarlas sin cambiar su alcance funcional.
3. IF dos reglas pueden interpretarse como incongruentes THEN la variante compacta SHALL expresar una prioridad o formulación inequívoca, en vez de eliminar silenciosamente una obligación esencial.
4. WHEN se preparan las variantes THEN el experimento SHALL conservar artefactos identificables del prompt actual y del candidato para que los resultados puedan asociarse a la variante correcta.

### Requisito 3: Medición y análisis de latencia
**Objective:** Como responsable del experimento, quiero registrar métricas por inferencia y agregarlas de manera robusta, para saber si la mejora proviene del prefill o de la generación.

#### Acceptance Criteria
1. WHEN termina una inferencia THEN el experimento SHALL registrar variante, duración LLM, duración total, `prompt_tokens`, `completion_tokens`, `total_tokens` y `finish_reason`, cuando el backend los proporcione.
2. IF el backend expone TTFT THEN el experimento SHALL registrar también TTFT y tokens por segundo; IF no lo expone THEN el informe SHALL marcar esas métricas como no disponibles.
3. WHEN se comparan variantes THEN el experimento SHALL ejecutar al menos cinco pares de muestras alternando el orden de las variantes y SHALL reportar mediana y rango por métrica.
4. WHEN el informe interpreta el resultado THEN el informe SHALL separar cambios en tokens/latencia de entrada (prefill) de cambios en tokens/latencia de salida (generación) y SHALL indicar las limitaciones de variabilidad del modelo.
5. IF solo existe una muestra por variante THEN el informe SHALL identificarla como exploratoria y SHALL abstenerse de concluir que el cambio causó una mejora.

### Requisito 4: Calidad y no regresión
**Objective:** Como responsable de Airi, quiero comprobar que la optimización no empeore las respuestas, para no intercambiar calidad por velocidad sin evidencia.

#### Acceptance Criteria
1. WHEN se evalúa cada respuesta THEN el experimento SHALL verificar parseo y conformidad con el esquema de salida, relevancia respecto al mensaje, cumplimiento de reglas esenciales y proporcionalidad de la respuesta.
2. WHEN se comparan resultados THEN el informe SHALL presentar las evaluaciones de calidad junto a las métricas de rendimiento, sin tratar menor latencia como éxito si falla una regla esencial o el esquema.
3. IF la variante compacta produce una regresión de calidad THEN el informe SHALL identificar el criterio afectado y SHALL considerar el candidato no aceptable aunque mejore la latencia.

### Requisito 5: Privacidad y reproducibilidad
**Objective:** Como responsable del proyecto, quiero preservar la privacidad del contexto de la traza y poder repetir el análisis, para que el experimento sea seguro y verificable.

#### Acceptance Criteria
1. WHEN se guardan o muestran resultados THEN el experimento SHALL guardar métricas agregables y metadatos de variante sin exponer el texto privado de entrada, historial o respuesta.
2. WHEN se repite una ejecución THEN el experimento SHALL identificar la traza de origen, variante, configuración relevante, orden y número de muestra.
3. IF faltan métricas de uso o de tiempo del backend THEN el informe SHALL señalar explícitamente los campos ausentes y SHALL evitar sustituirlos por valores inferidos.

### Requisito 6: Candidata focalizada para decisiones conversacionales sencillas
**Objective:** Como responsable del experimento, quiero probar una formulación del prompt que no invite a comparar opciones de GIF ni a escoger gestos innecesarios, para evaluar si reduce la deliberación de la llamada primaria sin alterar el prompt de producción.

#### Acceptance Criteria
1. WHEN se construye `decision_light_candidate` THEN la selección del GIF SHALL basarse en la acción o emoción observable de la respuesta, sin exigir que coincida literalmente con `mood.label` ni presentar pares de GIF como una decisión que deba optimizarse.
2. WHEN se genera `reply` THEN las acciones narrativas entre asteriscos SHALL ser opcionales y el prompt SHALL favorecer una respuesta natural y proporcionada sin exigir búsqueda de formulaciones alternativas.
3. WHEN se compara la nueva candidata THEN el experimento SHALL mantener byte por byte `current`, el schema, los enums, el historial, el modelo y los parámetros de inferencia sin cambios.
4. WHEN se analizan las métricas THEN el informe SHALL separar la llamada `primary` de las llamadas posteriores de reparación o revisión y SHALL registrar tokens, duración, parseo, truncamiento y reparaciones disponibles para cada muestra.

### Requisito 7: Promoción aprobada de la guía al prompt de producción
**Objective:** Como responsable de Airi, quiero llevar al prompt `current` la guía experimental aprobada, para que el bot use la formulación validada sin depender de un selector de replay.

#### Acceptance Criteria
1. WHEN se construye el prompt `current` THEN SHALL indicar que el GIF debe ser un valor canónico permitido, escogido por la reacción observable, sin exigir coincidencia con `mood.label`.
2. WHEN se construye el prompt `current` THEN SHALL presentar como suficiente una respuesta cotidiana, directa y proporcionada, y SHALL aclarar que los gestos narrativos son opcionales.
3. WHEN el parser recibe los alias `smile` o `neutral` THEN SHALL normalizarlos respectivamente a `happy` y `nod` antes de validar/enrutar; los valores canónicos como `shy` SHALL permanecer iguales y los desconocidos SHALL conservar el fallback seguro.
4. WHEN se adopta la guía en producción THEN SHALL conservar el schema, los enums canónicos, las claves obligatorias y la política de parse-repair para JSON inválido o truncado.
5. WHEN se valida el cambio THEN SHALL comprobarse la igualdad de los contratos y la ruta de rollback/comparación con la guía anterior; la normalización de GIF SHALL NOT considerarse una reducción del razonamiento ni una reparación de JSON.

### Requisito 8: Semántica visual centralizada de GIF
**Objective:** Como responsable de Airi, quiero que cada GIF tenga un significado visual observable definido en un único lugar, separado del ánimo interno, para que la elección sea contextual y no invite a comparar alternativas equivalentes.

#### Acceptance Criteria
1. WHEN se construye cualquier variante activa del system prompt THEN SHALL existir una única sección principal titulada `=== REACCIONES VISUALES Y SELECCIÓN DE GIF ===` que distinga intención conversacional, ánimo interno y reacción visual observable.
2. WHEN se presenta el catálogo semántico THEN SHALL cubrir todos los GIF canónicos permitidos por `ALLOWED_GIF_TYPES`, excepto `none` si este no representa una reacción; SHALL preservar cada identificador/API y SHALL asignar significados observables acordes al catálogo aprobado por el usuario.
3. WHEN el modelo selecciona un GIF THEN SHALL priorizar la intención y la reacción observable coherente con `reply`; el ánimo será contexto complementario y no una correspondencia fija ni una selección automática por palabra clave.
4. WHEN se describe `shy` THEN SHALL significar sonrojo, vergüenza o pudor visible; la etiqueta o estado interno `timida` por sí solo SHALL NOT obligar a elegir `shy`. `wave` SHALL conservar el significado gestual de saludo/despedida.
5. WHEN se construye el fragmento dinámico `ÁNIMO DE ESTE TURNO` THEN SHALL expresar el ánimo mediante tono y actitud, indicar que el GIF refleja una reacción observable coherente con `reply` y que no necesita coincidir con `mood.label`, y SHALL NOT indicar ni forzar un GIF. SHALL conservar instrucciones existentes de afinidad/cercanía social.
6. WHEN se describe el campo JSON `gif` THEN SHALL conservar la lista completa de valores permitidos y limitar su descripción a identificar la reacción visual que acompaña `reply` y remitir a la sección semántica centralizada; no SHALL duplicar definiciones de GIF ni reglas de comparación.
7. WHEN se ensamblan variantes full, compactas, experimentales o de rollback THEN SHALL evitar secciones duplicadas y guía antigua contradictoria, incluida la antigua `Guía de GIFs` y cualquier asociación ambigua de `wave`/`shy`.
8. WHEN se valida la implementación THEN SHALL comprobar con el prompt capturado desde una petición real la unicidad de la sección, cobertura de IDs, independencia ánimo/GIF, JSON, `finish_reason` y presencia de `content`; SHALL probar repetidamente los seis escenarios aprobados y reportar frecuencia de reconsideración de GIF, tokens de razonamiento, bucles, coherencia y calidad.
9. WHEN se reportan resultados comparativos THEN SHALL usar el mismo modelo y parámetros y distinguir medición exploratoria de evidencia estadística; no SHALL afirmar mejora pre/post si no existen condiciones equivalentes.
10. WHEN se modifica esta guía THEN SHALL preservarse contrato JSON, personalidad, afinidad, romance, memoria, parámetros llama.cpp y flujo de parse/retry existentes; no SHALL agregarse razonamiento paso a paso, reglas deterministas por palabra ni mecanismos de reintento o detección de bucles.
