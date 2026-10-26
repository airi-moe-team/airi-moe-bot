# Feedback Report — airi-interaccion-natural

**Generado:** 2026-10-24T07:03:01Z  
**Total items:** 8  
**Severidad:** major (6), minor (2)

## Resumen
Feedback consolidado sobre la spec `airi-interaccion-natural`, a partir del análisis de la traza `88f9f88c0ee0`, la evaluación cualitativa de ~64% de humanidad conversacional y los riesgos técnicos/metodológicos identificados.

## Aprobaciones a resetear
- requirements
- design
- tasks

## Detalle

### FB-009 — Respuesta directa a la intención del disparador en intervenciones espontáneas
- **Severidad:** major
- **Impacto:** Las intervenciones espontáneas pueden devolver preguntas o cambiar de tema antes de atender el estímulo que activó el turno.
- **Recomendación:** Añadir criterio de aceptación para que la respuesta espontánea atienda primero el mensaje activador y el contexto efímero.

**Actualizaciones propuestas:**
- **requirements:** Requirement 3: añadir criterio de aceptación para respuesta directa a la intención del disparador.
- **design:** Definir regla de prioridad de intención en el prompt de intervención espontánea.
- **tasks:** Añadir pruebas de pregunta directa y corrección en intervenciones espontáneas.

### FB-010 — Naturalidad narrativa y brevedad proporcional en intervenciones
- **Severidad:** major
- **Impacto:** Las respuestas espontáneas pueden acumular gestos, fórmulas genéricas y cierres prefabricados.
- **Recomendación:** Reforzar la regla existente para que las acotaciones sean opcionales y la extensión sea proporcional.

**Actualizaciones propuestas:**
- **requirements:** Requirement 3: la respuesta espontánea debe ajustar su extensión al contexto y evitar acotaciones por inercia.
- **design:** Consolidar política de naturalidad narrativa sin duplicar instrucciones.

### FB-011 — Coherencia entre texto, disconnect, stay_active y estado real
- **Severidad:** major
- **Impacto:** La traza muestra `disconnect.leave=false` y `stay_active=false` junto a un estado persistido de apagado confirmado.
- **Recomendación:** Investigar el flujo completo antes de corregir; no resolver solo con prompt.

**Actualizaciones propuestas:**
- **design:** Documentar flujo de `disconnect`/`stay_active` y persistencia de actividad.
- **tasks:** Añadir casos técnicos para combinaciones de `disconnect` y `stay_active`.

### FB-012 — Memoria consolidada y preferencias corregidas
- **Severidad:** minor
- **Impacto:** Los recuerdos duplicados o contradictorios reducen la personalización.
- **Recomendación:** Definir consolidación con precedencia para correcciones explícitas.

**Actualizaciones propuestas:**
- **requirements:** Añadir criterio de respeto a correcciones explícitas de preferencias.
- **design:** Definir modelo de consolidación de recuerdos.
- **tasks:** Añadir pruebas de aislamiento entre usuarios y preferencias contradictorias.

### FB-013 — Pruebas de regresión y métricas de naturalidad
- **Severidad:** minor
- **Impacto:** No hay evidencia reproducible de mejora de naturalidad tras cambios de prompt.
- **Recomendación:** Crear escenarios fijos y puntuar comprensión, naturalidad, continuidad, individualidad y coherencia.

**Actualizaciones propuestas:**
- **tasks:** Añadir escenarios de pregunta directa, corrección, saludo breve, preferencia corregida, desacuerdo, conversación casual y despedida.

### FB-014 — Evaluación reproducible A/B del prompt
- **Severidad:** major
- **Impacto:** Los cambios de naturalidad podrían parecer mejores en ejemplos aislados, pero empeorar otros escenarios o depender de la variabilidad de generación.
- **Recomendación:** Establecer línea base con el prompt actual y ejecutar los mismos casos con el prompt modificado.

**Actualizaciones propuestas:**
- **requirements:** Exigir evidencia comparativa de mejora antes de aprobar cambios de naturalidad.
- **design:** Definir un evaluador que registre entradas, contexto, versión del prompt, configuración del modelo y resultados.
- **tasks:** Crear conjunto de pruebas de referencia y comparar baseline frente a candidato.

### FB-015 — Integridad del contrato de salida y del estado
- **Severidad:** major
- **Impacto:** Una respuesta puede sonar natural, pero contener campos inesperados, valores incompatibles o decisiones de actividad mal interpretadas.
- **Recomendación:** Verificar que la salida cumpla el esquema vigente y que normalización, acciones y persistencia sean coherentes.

**Actualizaciones propuestas:**
- **design:** Documentar el flujo entre generación, validación, normalización, ejecución de acciones y persistencia.
- **tasks:** Probar JSON inválido, campos ausentes, campos desconocidos, valores nulos y combinaciones de `disconnect` y `stay_active`.

### FB-016 — Separación entre escucha activa e intervención espontánea
- **Severidad:** major
- **Impacto:** Mejorar la naturalidad podría hacer que Airi responda demasiado o intervenga cuando no debería.
- **Recomendación:** Evaluar por separado selección del estímulo, decisión de intervenir y generación del mensaje.

**Actualizaciones propuestas:**
- **requirements:** Conservar las condiciones que determinan cuándo Airi debe intervenir y cuándo permanecer escuchando.
- **design:** Separar la selección del disparador de la política lingüística que redacta la respuesta.
- **tasks:** Probar mensajes irrelevantes, conversaciones entre otros usuarios, estímulos relevantes, mensajes consecutivos y ausencia de objetivo narrativo.
### FB-017 — Ajustes finales de precisión y salvaguardas
- **Severidad:** major
- **Impacto:** Los requisitos podrían interpretarse de forma demasiado amplia y generar intervenciones innecesarias, conclusiones prematuras sobre FB-011, pérdida de evidencia A/B o mezcla de memoria entre usuarios.
- **Recomendación:** Refinar FB-009, FB-011, FB-014 y FB-016, y añadir salvaguardas transversales de memoria y evaluación.

**Actualizaciones propuestas:**
- **requirements:** FB-009: responder primero a la intención del mensaje activador, pero permitir preguntas cuando sean realmente útiles.
- **requirements:** FB-011: tratar la discrepancia observada como hipótesis por investigar, no como prueba definitiva de fallo.
- **requirements:** FB-014: guardar salidas originales, prompt efectivo, contexto, parámetros de inferencia y versión del modelo.
- **requirements:** FB-016: medir por separado si Airi debe intervenir y cómo redacta el mensaje.
- **requirements:** Memoria: una corrección explícita debe prevalecer sobre un recuerdo contradictorio dentro de su ámbito.
- **requirements:** Evaluación: una mejora media no debe ocultar regresiones graves.
- **design:** Documentar ajustes finales y salvaguardas transversales.
- **tasks:** Añadir verificación temporal de `last_shutdown`, artefactos completos de línea base y pruebas de aislamiento/regresiones graves.
