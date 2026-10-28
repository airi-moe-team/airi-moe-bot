# Requirements Document

## Introducción

Airi es la persona que habla en el canal de Discord. Hoy recibe el instante del turno
(`now`) en toda la tubería —`ConversationService.generate_turn`,
`services/conversation.py`—, pero ese dato nunca llega al prompt: no sabe la fecha ni la
hora, no distingue madrugada de tarde y no puede saber si alguien le escribió hace dos
minutos o hace tres días. El único tiempo que percibe es el relativo de sus entradas de
diario y memorias (`format_relative_time`, `domain/diary.py`) y los días de noviazgo
(`relationship_status_section`, `domain/prompts.py`).

Este incremento añade **percepción temporal** en tres capas:

- **L1 — Reloj**: fecha, hora local y franja del día.
- **L2 — Intervalos vividos**: silencio desde el último mensaje de la persona y desde la
  última actividad del canal.
- **L3 — Cadencia del historial**: marcas de tiempo relativas por intervención en la
  vista de inferencia.

El valor esperado es naturalidad: que Airi pueda decir "¿qué haces despierto a estas
horas?" o "pensaba que ya no aparecerías" con fundamento, sin recitar nunca el reloj ni
inventar el paso del tiempo.

## Requisitos

### Requirement 1: Reloj y contexto del momento (L1)

**Objective:** Como miembro del canal, quiero que Airi sepa qué día y qué hora son, para
que sus saludos, su energía y sus referencias encajen con el momento real.

#### Acceptance Criteria

1. WHEN se construye el prompt de sistema de un turno THEN Airi SHALL recibir la fecha
   local (día de la semana, día, mes y año) y la hora local del turno.
2. WHEN se construye el prompt de sistema THEN Airi SHALL recibir la franja del día
   correspondiente a esa hora local, con al menos cuatro valores: madrugada, mañana,
   tarde y noche.
3. IF el instante del turno cae exactamente en una frontera de franja THEN el sistema
   SHALL asignar la franja de forma determinista y documentada, sin ambigüedad.
4. WHERE `AIRI_TIMEZONE` no está definida THE sistema SHALL usar la zona horaria del
   sistema operativo.
5. WHERE `AIRI_TIMEZONE` está definida con una zona IANA válida THE sistema SHALL usar
   esa zona para fecha, hora y franja.
6. IF `AIRI_TIMEZONE` contiene un valor inválido THEN el sistema SHALL ignorarlo, avisar
   una sola vez y continuar con la zona del sistema, sin abortar el turno.
7. WHEN el prompt incluye la sección temporal THEN esa sección SHALL indicar
   explícitamente que la hora es contexto y no un dato que anunciar.
8. WHEN Airi responde en un turno con sección temporal THEN la respuesta SHALL NOT
   recitar la hora exacta ni afirmar que consulta un reloj o un calendario, salvo que el
   usuario pregunte directamente por la hora o la fecha.
9. IF el usuario pregunta directamente la hora o la fecha THEN Airi SHALL poder
   responder con el dato real disponible en su contexto temporal.

### Requirement 2: Intervalos vividos (L2)

**Objective:** Como interlocutor, quiero que Airi note cuánto tiempo ha pasado desde
nuestra última conversación y desde la última actividad del canal, para que reaccione
como alguien que ha vivido ese hueco.

#### Acceptance Criteria

1. WHEN Airi va a responder a una persona THEN su prompt SHALL incluir cuánto tiempo ha
   pasado desde el último mensaje registrado de esa persona en el canal, si existe.
2. WHEN Airi va a responder THEN su prompt SHALL incluir cuánto tiempo ha pasado desde
   la última actividad registrada en el canal, si existe, contando tanto el historial
   persistido como el búfer pasivo del modo espectador.
3. IF es la primera interacción con esa persona THEN el prompt SHALL indicarlo como
   primera vez y SHALL NOT inventar un intervalo previo.
4. WHEN el intervalo es inferior a una hora THEN el prompt SHALL expresarlo en minutos.
5. WHEN el intervalo es inferior a dos días THEN el prompt SHALL expresarlo en horas.
6. WHEN el intervalo es igual o superior a dos días THEN el prompt SHALL expresarlo en
   días, usando "ayer" solo para el día natural anterior.
7. IF el instante de referencia es anterior al último mensaje (reloj hacia atrás,
   datos de replay) THEN el prompt SHALL tratar el intervalo como "ahora mismo" y
   SHALL NOT mostrar valores negativos.
8. WHEN Airi mantiene una relación de pareja THEN el prompt SHALL seguir mostrando los
   días transcurridos desde el inicio de la relación, sin duplicar esa información en la
   sección temporal.
9. WHEN el turno se genera en modo `proactive` THEN la sección temporal SHALL incluir la
   franja del día y el silencio del canal, para que la iniciativa sea coherente con la
   hora.

### Requirement 3: Cadencia del historial (L3)

**Objective:** Como interlocutor, quiero que Airi perciba el ritmo de la conversación
—mensajes seguidos, pausas largas, reapariciones—, para que no trate igual un intercambio
rápido que un mensaje que llega tres días después.

#### Acceptance Criteria

1. WHEN se construye la vista de inferencia del historial THEN cada intervención de
   usuario o de espectador que tenga marca temporal conocida SHALL llevar una etiqueta
   de tiempo relativo a la hora del turno, con el mismo formato de intervalo del
   Requisito 2.
2. THE intervenciones de Airi SHALL NOT llevar prefijo temporal: su contenido es el
   contrato JSON de salida y debe conservarse intacto para no enseñar al modelo a
   anteponer etiquetas a su propia respuesta.
3. WHEN una intervención no tiene marca temporal THEN la vista SHALL incluirla sin
   etiqueta de tiempo, sin inventar valores.
4. WHEN la etiqueta temporal ya está presente en el contenido THEN la vista SHALL NOT
   duplicarla (idempotencia), igual que ocurre con la etiqueta de identidad.
5. THE historial canónico persistido SHALL NOT contener etiquetas de tiempo; las
   etiquetas SHALL reconstruirse en cada inferencia y SHALL NOT guardarse en disco.
6. THE etiquetas de tiempo SHALL ser deterministas para el mismo historial y el mismo
   instante de turno.
7. WHERE el historial no tiene marcas temporales (estado antiguo o trazas previas) THE
   sistema SHALL seguir funcionando y SHALL NOT añadir etiquetas.
8. IF el texto de un usuario imita el formato de la etiqueta temporal THEN el sistema
   SHALL tratarlo como contenido del usuario y SHALL NOT confundirlo con metadatos
   internos.

### Requirement 4: Coherencia por modo conversacional

**Objective:** Como miembro del canal, quiero que la percepción temporal esté presente
en todos los modos —normal, breve, espectador, conversación activa e iniciativa
proactiva— para que Airi no cambie de personalidad temporal según el modo.

#### Acceptance Criteria

1. WHEN Airi responde en un turno normal THEN el prompt SHALL incluir la sección
   temporal completa.
2. WHEN Airi responde en un turno `quick` THEN el prompt SHALL incluir una versión
   reducida de la sección temporal que conserve al menos fecha, hora, franja y el
   silencio de la persona.
3. WHEN Airi responde en modo `spectator` o `active` THEN el prompt SHALL incluir la
   sección temporal completa, calculada con el instante del turno.
4. WHEN Airi inicia una conversación en modo `proactive` THEN el prompt SHALL incluir la
   franja del día y SHALL NOT proponer planes propios de otra franja (por ejemplo,
   planes diurnos en madrugada).
5. WHEN una cita está en curso THEN la sección temporal SHALL NOT alterar los límites de
   duración ni los tiempos de la máquina de estados de citas.

### Requirement 5: Configuración, activación y rollback

**Objective:** Como responsable del bot, quiero poder activar, desactivar y comparar la
percepción temporal sin desplegar código, para medir su efecto y revertir rápido.

#### Acceptance Criteria

1. WHERE `AIRI_TIME_CONTEXT` está activo THE sistema SHALL inyectar todas las capas
   temporales (L1, L2 y L3).
2. WHEN `AIRI_TIME_CONTEXT` está desactivado THEN el prompt SHALL NOT contener ninguna
   sección temporal y la vista de inferencia SHALL NOT contener etiquetas de tiempo.
3. WHEN `AIRI_TIME_CONTEXT` está desactivado THEN el resto del comportamiento de Airi
   SHALL permanecer idéntico al actual.
4. IF `AIRI_TIME_CONTEXT` contiene un valor no reconocido THEN el sistema SHALL usar el
   valor por defecto documentado y avisar una sola vez.
5. THE valor por defecto de `AIRI_TIME_CONTEXT` SHALL estar documentado en `.env.example`
   junto con `AIRI_TIMEZONE`.
6. WHEN el bot arranca THEN SHALL registrar en el log la zona horaria resuelta y su
   origen (`AIRI_TIMEZONE` o sistema), para detectar contenedores en UTC.

### Requirement 6: Determinismo, replay y trazabilidad

**Objective:** Como responsable técnico, quiero que la percepción temporal no rompa la
reproducibilidad de trazas ni el benchmark, y que quede registrada para poder auditar
qué vio Airi en cada turno.

#### Acceptance Criteria

1. THE cálculo de fecha, hora, franja e intervalos SHALL derivarse exclusivamente del
   instante del turno inyectado, sin leer el reloj del sistema dentro del dominio.
2. WHEN se reproduce una traza existente con `python -m airi.replay` THEN el resultado
   SHALL seguir coincidiendo con el registrado.
3. WHEN se genera un turno THEN la traza SHALL registrar la fecha local, la franja, el
   silencio de la persona en minutos y el silencio del canal en minutos usados en el
   prompt.
4. THE traza SHALL NOT registrar contenido de mensajes añadido por esta feature más allá
   de los valores temporales anteriores.
5. WHEN el prompt se construye dos veces con el mismo estado y el mismo instante THEN el
   texto temporal SHALL ser idéntico byte a byte.

### Requirement 7: No regresión del contrato y de las reglas existentes

**Objective:** Como responsable del bot, quiero que añadir tiempo no cambie el contrato
de salida ni las reglas de afinidad, citas y relación, para no introducir regresiones.

#### Acceptance Criteria

1. THE esquema JSON de respuesta del LLM SHALL permanecer sin cambios.
2. THE lógica de afinidad, decay, citas, relación y memorias SHALL permanecer sin
   cambios funcionales.
3. WHEN el modelo devuelve una respuesta válida THEN el parseo SHALL comportarse igual
   con la feature activa y desactivada.
4. THE secciones de prompt existentes SHALL conservar su orden relativo; la sección
   temporal SHALL insertarse en una posición estable y documentada.

### Requirement 8: Evaluación de naturalidad temporal

**Objective:** Como responsable del bot, quiero escenarios reproducibles que permitan
comparar con y sin percepción temporal, para decidir con evidencia si mejora la
naturalidad.

#### Acceptance Criteria

1. THE repositorio SHALL incluir escenarios de evaluación con instantes fijos que cubran
   al menos: madrugada, mañana, tarde, noche, mensaje dos minutos después del anterior,
   reaparición tras tres días y turno proactivo nocturno.
2. WHEN se ejecuta la evaluación con la feature activa y desactivada con los mismos
   instantes THEN los resultados SHALL ser comparables por escenario.
3. THE evaluación SHALL verificar de forma determinista la ausencia de recitado del
   reloj en las respuestas, mediante reglas comprobables, no mediante juicio subjetivo.
4. IF un escenario no puede evaluarse por falta de datos THEN el sistema SHALL reportarlo
   como no evaluable en lugar de asumir éxito.
