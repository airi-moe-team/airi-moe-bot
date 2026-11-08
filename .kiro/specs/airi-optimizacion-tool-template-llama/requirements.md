# Documento de requisitos

## Introducción

Airi usa un adaptador HTTP común para llama.cpp y proveedores compatibles. Experimentos del usuario indican que declarar una herramienta junto con `tool_choice="none"` podría reducir respuestas que consumen el presupuesto completo de generación sin contenido visible. El usuario solicita integrar este comportamiento para llama.cpp sin variable de entorno. Un piloto emparejado de un saludo con `ConversationService` y el modelo real confirmó que la declaración se aplica a la llamada principal con JSON conversacional y que el parser acepta ambas respuestas; una sola pareja no prueba estabilidad general. Se deben preservar el razonamiento, las instrucciones y los contratos de respuesta actuales.

## Requisitos

### Requisito 1: Integración para llama.cpp sin configuración adicional
**Objetivo:** Como operador de Airi, quiero que el comportamiento se aplique automáticamente a las llamadas elegibles de llama.cpp sin configurar una variable adicional, sin alterar otros proveedores.

#### Criterios de aceptación
1. WHEN el proveedor es `llama` AND la solicitud es elegible THEN el adaptador SHALL declarar la herramienta sintética sin requerir variable de entorno.
2. WHEN el proveedor no es `llama` THEN el adaptador SHALL conservar el payload y comportamiento previos.
3. WHEN la solicitud usa herramientas reales o un `tool_choice` explícito THEN el adaptador SHALL conservar el contrato solicitado sin inyección sintética.
4. WHEN se elimina `LLM_TOOL_TEMPLATE_OPTIMIZATION` THEN ninguna configuración residual SHALL cambiar el comportamiento del adaptador.

### Requisito 2: Declaración no ejecutable de la herramienta
**Objetivo:** Como operador, quiero que llama.cpp reciba una declaración de herramienta experimental, para evaluar el efecto de su plantilla sin conceder capacidades adicionales al modelo.

#### Criterios de aceptación
1. WHEN una solicitud de llama.cpp es elegible THEN el adaptador SHALL declarar exactamente una herramienta de función `get_datetime` con la descripción y esquema de parámetros aprobados, y SHALL enviar `tool_choice` con valor `none`.
2. WHILE la herramienta experimental esté declarada THE sistema SHALL NOT ejecutarla ni permitir que acceda al sistema, a servicios externos o a estado de Airi.
3. IF el proveedor devuelve `tool_calls` para la herramienta experimental THEN el adaptador SHALL registrar la anomalía sin incluir contenido sensible y SHALL impedir que la llamada llegue a cualquier ejecutor de herramientas.
4. IF una solicitud ya contiene herramientas reales THEN el adaptador SHALL preservar sus definiciones y políticas y SHALL NOT sobrescribirlas, duplicar nombres ni sustituirlas por la herramienta experimental.

### Requisito 3: Preservación del contrato de generación
**Objetivo:** Como mantenedor, quiero que la optimización no altere las instrucciones ni la semántica de las solicitudes existentes, para limitar el experimento al metadato de declaración de herramientas.

#### Criterios de aceptación
1. WHEN se compara la variante declarativa con el payload anterior THEN el adaptador SHALL enviar mensajes idénticos en roles y contenidos.
2. WHEN se aplica la optimización THEN el adaptador SHALL preservar `chat_template_kwargs`, thinking, límites de tokens, muestreo, streaming y demás parámetros existentes.
3. WHEN se aplica la optimización THEN el sistema SHALL NOT modificar el system prompt, personalidad, biografía, memoria, historial, identidad de usuarios ni instrucciones de formato.
4. WHEN la conversación normal requiere una respuesta JSON estructurada (`schema` o `strict_schema`) THEN la declaración sintética SHALL poder aplicarse a la llamada principal de llama.cpp sin retirar el esquema ni alterar el parser, los validadores y la recuperación.
5. IF llama-server rechaza la combinación o una validación detecta un fallo atribuible a la declaración THEN el sistema SHALL conservar el manejo seguro de errores y no ejecutar la herramienta ficticia; un despliegue estable requiere evidencia adicional.

### Requisito 4: Compatibilidad de respuesta, streaming y recuperación
**Objetivo:** Como mantenedor, quiero que las respuestas sigan recorriendo los mecanismos existentes, para conservar la extracción de contenido y razonamiento, validación y recuperación.

#### Criterios de aceptación
1. WHEN se procesa una respuesta THEN el adaptador SHALL mantener separados `reasoning_content` y `content` y SHALL conservar la interpretación de `finish_reason` y `usage`.
2. WHEN una solicitud usa streaming THEN el adaptador SHALL preservar el ensamblado SSE, la medición de primer token y primer contenido visible, el tratamiento de respuestas vacías y el manejo de errores existentes.
3. IF una respuesta incluye una llamada inesperada a la herramienta experimental THEN el sistema SHALL aplicar la ruta segura de validación o recuperación existente y SHALL NOT tratarla como respuesta conversacional válida ni ejecutarla.
4. WHEN una respuesta falla validación o parsing THEN el sistema SHALL conservar los mecanismos existentes de validación y recuperación.

### Requisito 5: Evaluación comparativa y observabilidad
**Objetivo:** Como operador, quiero comparar sistemáticamente la configuración activada y desactivada, para decidir si la optimización mejora la latencia sin degradar la calidad.

#### Criterios de aceptación
1. WHEN se registra una solicitud de benchmark THEN el registro SHALL permitir asociar un identificador de petición, proveedor, modelo, estado de optimización, cantidad de herramientas declaradas, tokens de entrada y salida, tokens de razonamiento si están disponibles, caracteres de razonamiento como métrica diferenciada, latencia al primer token, latencia al primer contenido visible, tiempo total, `finish_reason`, presencia de `tool_calls` y resultado de validación.
2. WHEN se registran métricas THEN el sistema SHALL evitar registrar indiscriminadamente prompts completos o información sensible y SHALL respetar la instrumentación opt-in y las políticas de privacidad existentes.
3. WHEN se compara la optimización THEN la evaluación SHALL usar la ruta real de `ConversationService`, el prompt completo de Airi, el mismo escenario y los parámetros estructurados equivalentes en ambos modos, y SHALL verificar en la traza de la llamada principal que OFF no declaró la herramienta y ON sí. La evaluación ampliada SHALL cubrir saludo, conversación casual o cumplido, pregunta factual, conversación emocional, historial largo y conversación multiusuario con etiquetas de identidad.
4. WHEN se realiza un piloto limitado THEN dos ejecuciones de escenario (una OFF y una ON) SHALL bastar para verificar aplicabilidad y parsing, no estabilidad. WHEN los recursos de inferencia lo permitan THEN la evaluación ampliada SHALL ejecutar al menos cinco repeticiones por modo y escenario y SHALL fijar la semilla si el backend ofrece un mecanismo compatible.
5. WHEN se valoran resultados THEN el informe SHALL considerar `finish_reason`, respuesta visible, validez de parsing, coherencia/persona, invocaciones de herramientas y latencia visible; SHALL NOT declarar éxito únicamente por reducir tokens ni estabilidad sin reproducibilidad suficiente.
