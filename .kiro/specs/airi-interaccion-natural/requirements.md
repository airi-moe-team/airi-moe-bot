# Requirements Document

## Introducción

Esta primera fase implementa la escucha activa de Airi en un canal de Discord: Airi
conserva temporalmente el contexto del chat sin generar una respuesta por cada mensaje y
solo abre un turno cuando una regla local detecta un estímulo relevante. El objetivo es
que pueda sentirse presente e inmersiva sin consumir llamadas al LLM durante la escucha
pasiva ni forzar conversación.

El alcance de esta fase se limita al buffer pasivo, los disparadores de intervención y
los controles de frecuencia. La retirada ante hostilidad, la mediación/DM, el retorno, y
los disparadores por inactividad o picos de actividad quedan fuera de esta primera fase.

El flujo actual pasa por `on_message` (`src/airi/discord_bot/client.py`), el debounce y
el dispatcher, `run_user_turn` (`src/airi/discord_bot/turn.py`) y
`ConversationService` (`src/airi/services/conversation.py`). El historial conversacional
existente sigue siendo distinto del buffer temporal de escucha pasiva.

## Requirements

### Requirement 1: Escucha pasiva y contexto temporal
**Objective:** Como miembro del canal, quiero que Airi lea la conversación sin responder
a cada mensaje, para que el chat fluya sin interrupciones artificiales.

#### Acceptance Criteria
1. WHEN un usuario envía un mensaje de texto en el canal autorizado y el modo espectador
   está activo, THEN el bot SHALL añadirlo al buffer temporal del canal sin invocar al
   LLM ni publicar una respuesta.
2. IF el mensaje proviene de un bot, está vacío, pertenece a otro canal o es un comando
   gestionado por el bot, THEN el bot SHALL excluirlo del buffer pasivo.
3. WHILE el buffer conserva mensajes pasivos, THE bot SHALL limitar su tamaño y descartar
   entradas anteriores a un TTL configurable.
4. IF se reinicia la conversación o la temporada, THEN el bot SHALL vaciar el buffer
   temporal correspondiente.
5. IF el modo espectador está desactivado, THEN el bot SHALL conservar el comportamiento
   de conversación configurado actualmente.

### Requirement 2: Disparadores locales de activación
**Objective:** Como miembro del canal, quiero que Airi pueda sumarse cuando me dirijo a
ella o cuando detecta algo relevante, para que su participación se sienta espontánea.

#### Acceptance Criteria
1. WHEN un mensaje contiene una mención directa a Airi, es una respuesta a un mensaje de
   Airi o la nombra explícitamente, THEN el bot SHALL habilitar un turno de Airi sin
   requerir coincidencia de tema ni afinidad.
2. WHEN un mensaje del buffer coincide con un tema positivo del perfil existente de
   gustos de Airi, THEN el bot SHALL considerar elegible una intervención espontánea,
   aunque el autor no tenga afinidad alta.
3. WHEN el autor alcanza el umbral configurable de afinidad, THEN el bot SHALL considerar
   elegible una intervención espontánea, aunque el mensaje no coincida con un tema de
   interés de Airi.
4. IF el tema positivo coincide OR el autor alcanza el umbral de afinidad, THEN el bot
   SHALL tratar la señal correspondiente como suficiente por sí sola para evaluar una
   intervención; no SHALL requerir que ambas condiciones se cumplan a la vez.
5. IF ninguna mención ni señal espontánea coincide, THEN el bot SHALL conservar el
   mensaje en el buffer y no SHALL generar un turno.
6. WHEN el bot detecta un tema de interés, THEN SHALL consultar los gustos positivos del
   perfil/self-model existente de Airi como fuente canónica y no SHALL mantener una lista
   duplicada de temas de activación.
7. WHILE se evalúa la coincidencia de tema, THE bot SHALL hacerlo SIN usar el LLM,
   mediante un matcher local de palabras clave y expresiones regulares precompiladas a
   partir del perfil positivo de Airi, con normalización de texto y límites de palabra.
8. IF el perfil de gustos de Airi cambia, THEN el bot SHALL refrescar el matcher
   precompilado para reflejar el perfil vigente.
9. IF un sinónimo o variante debe activar el disparador, THEN el bot SHALL exigir que el
   alias esté definido explícitamente en la configuración del matcher.

### Requirement 3: Generación contextual de la intervención
**Objective:** Como participante, quiero que Airi entienda de qué está hablando el grupo
cuando interviene, para que su respuesta encaje en la conversación.

#### Acceptance Criteria
1. WHEN un disparador habilita un turno, THEN el bot SHALL enviar al LLM el mensaje que
   activó el turno más una captura efímera de los mensajes recientes del buffer, con la
   atribución de sus autores, y cada mensaje SHALL aparecer exactamente una vez.
2. IF se construye esa captura efímera, THEN el bot SHALL separarla del historial
   conversacional persistente y NO SHALL volcar los mensajes pasivos a
   `state.histories[channel_id]` ni a la memoria de largo plazo.
3. WHEN la respuesta espontánea se publica con éxito, THEN el bot SHALL marcar como
   consumidos únicamente los mensajes incluidos en la captura efímera generada.
4. IF la generación falla o el turno no se publica, THEN el bot SHALL conservar en el
   buffer los mensajes no consumidos hasta que expire su TTL.
5. WHEN se prepara el turno, THEN el bot SHALL conservar el prompt habitual de
   personalidad, gustos y afinidad de Airi, pero no SHALL añadir instrucciones que
   revelen el umbral o la regla interna que causó la activación.
6. IF Airi interviene espontáneamente, THEN su respuesta SHALL reaccionar al tema con
   naturalidad y NO SHALL estar obligada a terminar con una pregunta.
7. IF un disparador no activa un turno, THEN el bot SHALL no invocar al LLM para ese
   mensaje.
8. IF se usa el buffer para generar una respuesta, THEN el bot SHALL evitar duplicar
   mensajes ya presentes en el historial conversacional existente.

### Requirement 4: Frecuencia, concurrencia y configuración
**Objective:** Como miembro del canal, quiero que Airi no monopolice la conversación,
para que sus intervenciones espontáneas sigan siendo ocasionales.

#### Acceptance Criteria
1. WHEN Airi publica una intervención espontánea, THEN el bot SHALL aplicar un cooldown
   configurable por canal y autor antes de permitir otra intervención espontánea.
2. IF hay un turno en curso o el mensaje sigue pendiente en debounce, THEN el bot SHALL
   esperar a que el turno termine antes de despachar otra intervención.
3. IF una mención directa o respuesta a Airi ocurre durante el cooldown espontáneo, THEN
   el bot SHALL conservar la prioridad de ese disparador explícito sin duplicar turnos.
4. WHEN una señal espontánea es elegible y no hay cooldown activo, THEN el bot SHALL
   aplicar una probabilidad configurable mediante una tirada local previa a cualquier
   llamada al LLM; los valores de reloj y azar SHALL poder inyectarse en tests para que
   el resultado sea reproducible.
5. IF la tirada de probabilidad falla, THEN el bot SHALL guardar silencio, NO SHALL
   invocar al LLM y NO SHALL iniciar el cooldown, de modo que el siguiente mensaje pueda
   volver a intentar la intervención.
6. WHEN la intervención se publica con éxito, THEN el bot SHALL iniciar el cooldown; si
   el turno no se publica, el cooldown SHALL no consumirse.
7. THE bot SHALL permitir configurar el modo espectador, el límite/TTL del buffer, el
   umbral de afinidad, las probabilidades de intervención y los cooldowns siguiendo el
   patrón de configuración existente.

### Requirement 5: Verificación y compatibilidad
**Objective:** Como desarrollador, quiero comprobar que Airi escucha sin gastar llamadas
innecesarias y que los nuevos disparadores no rompen el flujo actual.

#### Acceptance Criteria
1. WHEN un mensaje no tiene un disparador aplicable, THEN una prueba SHALL verificar que
   no se invoca al LLM y no se publica una respuesta.
2. WHEN un mensaje coincide solo con un tema positivo, THEN una prueba SHALL verificar
   que la señal de tema puede habilitar una intervención sin afinidad alta.
3. WHEN el autor supera solo el umbral de afinidad, THEN una prueba SHALL verificar que
   esa señal puede habilitar una intervención sin coincidencia de tema.
4. WHEN llega una mención directa o una respuesta a Airi, THEN una prueba SHALL verificar
   que activa un turno sin depender de las señales espontáneas.
5. WHEN se activa un cooldown, THEN una prueba SHALL verificar que mensajes elegibles
   repetidos no producen intervenciones espontáneas adicionales hasta que expire.
6. WHEN una tirada de probabilidad falla, THEN una prueba SHALL verificar que no se
   invoca al LLM y que el cooldown no se activa, permitiendo reintentar con el siguiente
   mensaje.
7. WHEN la intervención se publica con éxito, THEN una prueba SHALL verificar que solo
   los mensajes de la captura efímera se consumen y que el historial persistente no
   recibe los pasivos no incluidos.
8. WHILE se ejecuta la suite de tests, THE implementación SHALL mantener los tests
   existentes, usar los fakes de `airi/testing` y no requerir red ni Discord real.
