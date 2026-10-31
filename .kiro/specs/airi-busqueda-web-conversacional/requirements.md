# Requirements Document

## Descripción del proyecto

Cambiar la búsqueda web de Airi de un disparador determinista a una acción decidida por el modelo mediante tool calling nativo. Airi debe decidir cuándo saca el móvil a mitad de la charla, ejecutar `buscar_web(query, motivo)` y contar el resultado con su propia voz: motivación integrada, dato extraído, juicio propio y duda cuando las notas se contradicen. Sin regex que disparen búsquedas, sin frases de respuesta prefijadas y sin que el sistema reescriba la respuesta. El grounding solo se registra en traza.

## Introducción

Hoy la búsqueda web se activa con reglas léxicas (`src/airi/domain/web.py`), se reformula la consulta con una llamada extra, se inyectan resultados con reglas de "solo datos literales" y se sustituye la respuesta si un validador heurístico la considera no fundamentada. El resultado es un oráculo que entrega reportes. Esta feature convierte la búsqueda en una herramienta que Airi decide usar y cuyo resultado integra en la conversación con su propio criterio, sin perder la honestidad factual.

## Requisitos

### Requisito 1: Decisión de búsqueda propiedad del modelo

**Objetivo:** Como responsable del personaje, quiero que Airi decida por sí misma cuándo buscar, para que la búsqueda nazca de la conversación y no de una regla.

#### Criterios de aceptación

1. WHEN un turno admita búsqueda web THEN el sistema SHALL ofrecer la herramienta `buscar_web` al modelo y SHALL dejar la decisión de invocarla al modelo.
2. WHEN el sistema decida si busca THEN SHALL NOT usar expresiones regulares, listas de verbos ni `tool_choice` forzado por reglas léxicas.
3. WHEN el modelo invoque la herramienta THEN el sistema SHALL usar la `query` y el `motivo` generados por el modelo, sin reescribirlos.
4. WHEN el modelo no invoque la herramienta THEN el sistema SHALL continuar con la generación normal sin búsqueda.

### Requisito 2: Tool calling nativo compatible con llama.cpp

**Objetivo:** Como operador, quiero que la herramienta funcione con el backend local, para no añadir proveedores ni contratos ad hoc.

#### Criterios de aceptación

1. WHEN el cliente LLM envíe una petición con herramientas THEN SHALL usar el formato OpenAI `tools` y SHALL interpretar `message.tool_calls`.
2. WHEN el backend no soporte tool calling nativo THEN el sistema SHALL fallar de forma explícita y registrable, sin activar un camino alternativo silencioso.
3. WHEN se use `tools` THEN el sistema SHALL NOT enviar `response_format` en la misma petición salvo que el spike demuestre compatibilidad.
4. WHEN se use `tools` THEN el sistema SHALL NOT usar streaming en esa petición.

### Requisito 3: Notas de búsqueda sin formato de reporte

**Objetivo:** Como usuario, quiero recibir la información como algo que Airi acaba de ver, no como un listado de fuentes.

#### Criterios de aceptación

1. WHEN la búsqueda devuelva resultados THEN el sistema SHALL entregar al modelo notas compactas con título y extracto, sin URLs, sin ranking y sin numeración de fuentes.
2. WHEN la búsqueda no devuelva resultados THEN el sistema SHALL comunicar al modelo el estado vacío como un hecho estructurado, sin una frase de respuesta prefijada.
3. WHEN la búsqueda falle THEN el sistema SHALL registrar el fallo y SHALL permitir que el modelo lo cuente con sus propias palabras.

### Requisito 4: Síntesis reactiva con voz de Airi

**Objetivo:** Como usuario, quiero que Airi reaccione a lo que encuentra, para que la conversación siga siendo una conversación.

#### Criterios de aceptación

1. WHEN Airi use resultados de búsqueda THEN SHALL integrar en su respuesta el motivo por el que buscó, sin anunciar una consulta ni citar fuentes.
2. WHEN Airi use resultados de búsqueda THEN SHALL poder emitir una opinión o reacción subjetiva no presente en las notas.
3. WHEN Airi use resultados de búsqueda THEN SHALL NOT inventar datos concretos (nombres, fechas, precios, versiones) ausentes de las notas.
4. WHEN las notas contengan información contradictoria THEN Airi SHALL expresar duda y SHALL NOT presentar una versión como certeza.

### Requisito 5: Sin frases canónicas ni reescritura del sistema

**Objetivo:** Como responsable del personaje, quiero que ninguna respuesta de Airi sea un texto impuesto por el sistema.

#### Criterios de aceptación

1. WHEN un turno incluya búsqueda web THEN el sistema SHALL NOT sustituir la respuesta del modelo por un texto prefijado.
2. WHEN el validador heurístico detecte datos sospechosos THEN el sistema SHALL registrar la señal en la traza y SHALL NOT bloquear ni reescribir la respuesta.
3. WHEN se construya el prompt de búsqueda THEN SHALL describir el comportamiento esperado y SHALL NOT incluir respuestas de ejemplo entre comillas que el modelo pueda parafrasear.

### Requisito 6: Límites y modos

**Objetivo:** Como operador, quiero acotar la herramienta para que no degrade la conversación ni el coste.

#### Criterios de aceptación

1. WHEN un turno ya haya ejecutado una búsqueda THEN el sistema SHALL ignorar cualquier tool call adicional en ese turno.
2. WHEN `allow_web` sea falso (citas, sesiones, espectador) THEN el sistema SHALL NOT ofrecer la herramienta.
3. WHEN la herramienta se invoque THEN el sistema SHALL registrar query, motivo, latencia, backend y resultado.

### Requisito 7: Trazabilidad y evaluación

**Objetivo:** Como desarrollador, quiero poder verificar que la búsqueda es del modelo y que la voz no se rompe.

#### Criterios de aceptación

1. WHEN ocurra un turno con decisión de búsqueda THEN la traza SHALL incluir si hubo tool call, motivo, query, backend, resultado y señales de grounding.
2. WHEN se evalúe la feature THEN SHALL existir un conjunto de escenarios que cubra curiosidad, fallo de memoria, debate, contradicción, petición explícita, no búsqueda, búsqueda fallida y límites.
3. WHEN se evalúe la voz THEN la evaluación SHALL valorar la función (motivo integrado, reacción, duda) y SHALL NOT exigir frases literales.
