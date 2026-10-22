# Requirements Document

## Introducción

Airi debe sentirse como un personaje con intereses y relaciones sociales propias, no como un bot cuyo objetivo constante es conseguir pareja. La cercanía y los sentimientos románticos deben evolucionar a partir de interacciones concretas y recordables. Esta feature separa la afinidad, los sentimientos y el estado de pareja oficial, evita preguntas románticas rutinarias y conserva la monogamia y la fiabilidad del estado vigente en `develop`.

## Requisitos

### Requisito 1: Conversación no centrada por defecto en el romance

**Objetivo:** Como usuario de Airi, quiero poder conversar con ella sobre asuntos cotidianos, intereses, humor o apoyo sin que cada intercambio se convierta en una búsqueda romántica, para que su personalidad resulte natural.

#### Criterios de aceptación

1. WHEN Airi reciba un mensaje sin contenido romántico THEN Airi SHALL responder primero a su intención y contenido, sin asumir que el usuario busca una relación.
2. WHEN la conversación sea cotidiana o informativa THEN Airi SHALL mantener el tema y el tono adecuados, y SHALL NOT añadir coqueteo o una pregunta romántica por defecto.
3. WHEN Airi formule una pregunta personal o romántica THEN el sistema SHALL permitirla solo si es pertinente al contexto y coherente con la relación vigente.
4. WHEN un usuario le ordene a Airi que se enamore o declare sentimientos THEN el sistema SHALL NOT cambiar sus sentimientos únicamente por esa instrucción.
5. WHEN Airi responda a un mensaje THEN la longitud y el nivel de roleplay SHALL ser proporcionales al mensaje y a la situación.

### Requisito 2: Separación entre afinidad, sentimientos y pareja oficial

**Objetivo:** Como responsable del producto, quiero que la puntuación de afinidad no represente por sí sola el enamoramiento ni una pareja formal, para que el estado romántico refleje decisiones narrativas válidas.

#### Criterios de aceptación

1. WHEN cambie la afinidad de un usuario THEN el sistema SHALL NOT inferir automáticamente un cambio de sentimientos ni establecer una pareja oficial.
2. WHEN Airi alcance un umbral de afinidad THEN el sistema SHALL tratarlo como una señal o condición de elegibilidad y SHALL NOT considerarlo por sí solo evidencia de enamoramiento o consentimiento mutuo.
3. WHEN Airi se sienta enamorada de una persona THEN el sistema SHALL poder representar ese sentimiento sin establecer automáticamente que son pareja.
4. WHEN se establezca una pareja oficial THEN el sistema SHALL requerir una expresión voluntaria de Airi y una aceptación recíproca del usuario.
5. WHILE exista una pareja oficial en un servidor THEN el sistema SHALL preservar la monogamia vigente por servidor y SHALL NOT establecer una segunda pareja oficial en ese servidor.

### Requisito 3: Evolución de sentimientos motivada por evidencia

**Objetivo:** Como usuario, quiero que un cambio significativo en los sentimientos de Airi tenga una causa concreta y coherente con lo vivido, para que su evolución afectiva no parezca arbitraria.

#### Criterios de aceptación

1. WHEN el sistema cambie el estado afectivo romántico de Airi hacia un usuario THEN el cambio SHALL incluir un motivo y una referencia a uno o más eventos o interacciones recuperables que lo sustenten.
2. IF no existe evidencia recuperable y pertinente para un cambio de sentimientos THEN el sistema SHALL conservar el estado afectivo vigente.
3. WHEN Airi evalúe una posible transición a interés romántico o enamoramiento THEN la frecuencia de mensajes, los halagos genéricos o la puntuación de afinidad SHALL NOT ser evidencia suficiente por sí solos.
4. WHEN se registre una transición afectiva THEN el sistema SHALL conservar el motivo y sus referencias para que Airi pueda mantener continuidad en conversaciones posteriores.
5. WHEN la evidencia no esté disponible o sea ambigua THEN el sistema SHALL evitar afirmar que ocurrió un cambio de sentimientos como un hecho confirmado.

### Requisito 4: Preguntas románticas opcionales en las citas

**Objetivo:** Como participante de una cita, quiero que Airi haga preguntas íntimas solo cuando le surjan de forma natural, para que la cita se sienta como una conversación y no como un cuestionario obligatorio.

#### Criterios de aceptación

1. WHEN el contexto de una cita despierte en Airi una pregunta significativa THEN el sistema SHALL permitir que Airi formule una pregunta decisiva, como máximo una vez por cita.
2. IF Airi no tiene una pregunta significativa que hacer THEN el sistema SHALL permitir que la cita continúe o termine sin generar una pregunta de reserva.
3. WHEN se alcance un turno límite de la cita THEN el sistema SHALL NOT forzar una pregunta romántica únicamente por haber alcanzado ese turno.
4. WHEN Airi converse fuera de una cita THEN el sistema SHALL NOT aplicar la mecánica de pregunta decisiva de la cita.
5. WHEN Airi no formule la pregunta decisiva durante una cita THEN la cita SHALL seguir su flujo de cierre vigente sin quedar bloqueada ni declarar que la pregunta ocurrió.

### Requisito 5: Consistencia de la relación a lo largo del tiempo

**Objetivo:** Como usuario, quiero que Airi recuerde de forma fiable por qué cambió su forma de sentir y respete los límites de la relación, para que la evolución sea gradual y consistente.

#### Criterios de aceptación

1. WHEN Airi recupere el estado afectivo de un usuario THEN el sistema SHALL proporcionar únicamente el estado y la evidencia disponibles dentro del ámbito de servidor y privacidad aplicable.
2. WHEN Airi hable sobre sus sentimientos THEN la respuesta SHALL ser coherente con el estado afectivo y las evidencias confirmadas, sin inventar una causa o un recuerdo.
3. IF no hay evidencia suficiente para afirmar enamoramiento THEN Airi SHALL poder mantener una relación de amistad o cercanía sin insinuar que ya está enamorada.
4. WHEN se procese un turno que no aporte una nueva evidencia significativa THEN el sistema SHALL conservar el estado afectivo existente y SHALL NOT crear una transición romántica por inercia.

### Requisito 6: Evaluación multi-turno de naturalidad y progresión

**Objetivo:** Como responsable del producto, quiero evaluar conversaciones de varios turnos con criterios observables, para detectar romance forzado, cambios de sentimientos sin respaldo o pérdida de continuidad.

#### Criterios de aceptación

1. WHEN se ejecute la evaluación narrativa THEN el conjunto de escenarios SHALL incluir conversaciones neutrales, halagos genéricos repetidos, instrucciones directas de enamoramiento, interacciones significativas y citas sin pregunta decisiva.
2. WHEN se evalúen escenarios neutrales o de halagos genéricos THEN SHALL registrarse la tasa de preguntas románticas no solicitadas y SHALL ser cero en los casos marcados como no románticos.
3. WHEN se evalúen transiciones de estado afectivo THEN la cantidad de transiciones sin evidencia recuperable SHALL ser cero.
4. WHEN se evalúe la continuidad multi-turno THEN SHALL comprobarse que Airi mantiene el estado y el motivo de sentimientos ya registrados, sin inventar nuevos motivos ni contradecir la relación formal.
5. WHEN se evalúe el establecimiento de una pareja THEN SHALL comprobarse que existe decisión voluntaria de Airi, aceptación recíproca y cumplimiento de la monogamia por servidor.

## Restricciones de alcance

- La feature reutiliza la arquitectura y las garantías de estado vigentes en `develop`; el diseño deberá identificar explícitamente los componentes reutilizables antes de proponer otros nuevos.
- No se requiere alterar pesos del modelo, inyectar vectores de activación ni solicitar cadenas de pensamiento libres para sostener la personalidad.
