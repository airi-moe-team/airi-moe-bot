# Requirements Document

## Project Description (Input)
Nueva feature para evolucionar el modo espectador existente de Airi hacia una máquina de estados conversacional controlada parcialmente por el LLM. El comportamiento actual ya incluye PassiveBuffer volátil por canal con límite FIFO y TTL, snapshots, filtros locales de mención/handoff/tema/afinidad, cooldown y dispatch de turnos por canal. El alcance deseado: estados por canal Espectadora, Despertando, Activa y Retirada; al despertar inyectar snapshot y motivo (incluida inactividad proactiva configurable) en el contexto; solo marcar Activa tras generación y publicación exitosa; mientras Activa saltar el gating probabilístico/local y enviar mensajes agrupados por debounce al LLM, manteniendo filtros de seguridad, comandos y cola; permitir decisión estructurada del LLM para reply o silencio (reply null) y stay_active true/false; al retirarse limpiar el contexto activo y volver a Espectadora; timeout local configurable de inactividad total que fuerce retirada sin LLM. El estado conversacional debe ser volátil y por canal. No reutilizar el campo disconnect existente, ya que provoca apagado global del bot. Incluir manejo robusto del JSON inválido/fallos de LLM/publicación y pruebas unitarias/de integración del ciclo de vida. Respetar contratos y patrones existentes, especialmente client.py, turn.py, ConversationService, PassiveBuffer y llm_output.py. Feature name sugerido: airi-conversacion-activa-llm.

## Introduction

El modo espectador actual permite a Airi observar el canal autorizado sin llamar al LLM y despertar ante señales locales. Esta feature añade continuidad: una vez que Airi participa, el LLM decide si responde y si sigue en la conversación, mientras el sistema conserva filtros de entrada, serialización por canal y un límite local de inactividad. El estado conversacional será temporal, por canal y no persistido.

## Requirements

### Requirement 1: Observación pasiva y despertar
**Objective:** Como participante del canal, quiero que Airi escuche sin consumir inferencias y despierte por señales relevantes, para que su intervención sea oportuna y no invasiva.

#### Acceptance Criteria
1. WHILE el canal esté en estado Espectadora, THE Airi SHALL añadir los mensajes humanos elegibles al buffer pasivo existente y SHALL aplicar sus límites FIFO y TTL.
2. WHILE el canal esté en estado Espectadora, WHEN un mensaje no cumpla ninguna señal habilitada de mención, handoff, tema o afinidad, THEN Airi SHALL conservarlo en el buffer y SHALL NOT llamar al LLM por ese mensaje.
3. WHEN las reglas locales aprueben una señal de activación, THEN Airi SHALL iniciar un turno de despertar usando un snapshot vigente del buffer y SHALL incluir en el contexto el motivo de activación.
4. WHEN la activación se deba a inactividad proactiva configurable, THEN Airi SHALL iniciar el despertar sin exigir una señal de contenido y SHALL indicar explícitamente al LLM que puede proponer un tema nuevo.
5. WHEN se prepare un snapshot, THEN Airi SHALL respetar el límite de mensajes configurado y SHALL excluir mensajes ya incluidos en el turno que detonó el despertar.

### Requirement 2: Ciclo de vida por canal
**Objective:** Como operador del bot, quiero que cada canal tenga un estado conversacional explícito y efímero, para que la participación activa no se mezcle entre canales ni sobreviva indebidamente a reinicios.

#### Acceptance Criteria
1. THE Airi SHALL mantener para cada canal autorizado un estado entre Espectadora, Despertando, Activa y Retirada, junto con la información temporal mínima necesaria para gestionar la conversación; Retirada SHALL ser transitorio y SHALL devolver el canal a Espectadora después de limpiar el contexto activo.
2. WHEN un turno de despertar se inicia, THEN Airi SHALL marcar el canal como Despertando y SHALL evitar iniciar otro despertar concurrente para ese canal.
3. WHEN la respuesta del turno de despertar se publica correctamente, THEN Airi SHALL pasar el canal a Activa.
4. WHEN la generación o publicación del turno de despertar falla, THEN Airi SHALL NOT dejar el canal Activo y SHALL conservar los mensajes no consumidos según las reglas vigentes del buffer.
5. WHEN el proceso se reinicia, THEN Airi SHALL iniciar los canales en estado Espectadora y SHALL NOT restaurar estado activo desde disco.

### Requirement 3: Conversación activa dirigida por el LLM
**Objective:** Como participante, quiero que Airi pueda continuar una conversación natural y retirarse semánticamente, para no tener que volver a activar el modo espectador en cada turno.

#### Acceptance Criteria
1. WHILE un canal esté Activo, WHEN llegue un mensaje humano elegible, THEN Airi SHALL agruparlo mediante el debounce existente y SHALL enviarlo al LLM sin aplicar las probabilidades ni los filtros locales de tema/afinidad usados para despertar.
2. WHILE un canal esté Activo, THE Airi SHALL seguir aplicando la autorización de canal, el filtrado de bots y mensajes vacíos, el despacho de comandos y la cola FIFO por canal.
3. WHEN Airi solicite una respuesta en estado Activo, THEN el contrato estructurado del LLM SHALL permitir tanto un texto de respuesta como silencio explícito, y SHALL incluir una decisión booleana de permanecer Activo o retirarse.
4. WHEN el LLM indique permanecer Activo, THEN Airi SHALL mantener el canal Activo después de completar el turno, con independencia de que el LLM haya solicitado responder o guardar silencio.
5. WHEN el LLM indique retirarse, THEN Airi SHALL completar cualquier respuesta válida solicitada, SHALL volver el canal a Espectadora y SHALL limpiar el contexto temporal exclusivo de la conversación activa.
6. WHEN el LLM devuelva silencio explícito, THEN Airi SHALL NOT publicar un mensaje conversacional vacío ni un marcador literal de null.
7. IF la salida del LLM no cumple el contrato estructurado o la llamada falla, THEN Airi SHALL NOT ejecutar una retirada inferida de una salida inválida y SHALL dejar el canal en un estado seguro hasta una decisión válida o la expiración del timeout local.

### Requirement 4: Retirada por inactividad y activación proactiva
**Objective:** Como operador, quiero límites de tiempo configurables para la participación activa y la iniciativa, para evitar conversaciones abandonadas y permitir despertares ocasionales controlados.

#### Acceptance Criteria
1. WHILE un canal esté Activo, WHEN transcurra el timeout configurable sin mensajes humanos entrantes, THEN Airi SHALL forzar la transición a Espectadora sin llamar al LLM y SHALL limpiar el contexto activo.
2. WHILE un canal haya recibido actividad humana desde que el proceso inició y esté en estado Espectadora, WHEN transcurra el intervalo configurable sin nueva actividad humana, THEN Airi SHALL poder iniciar un despertar proactivo una sola vez para ese periodo de inactividad.
3. WHEN llegue un nuevo mensaje humano antes de vencer cualquiera de esos temporizadores, THEN Airi SHALL reiniciar el temporizador correspondiente y SHALL evitar que una tarea de temporizador obsoleta cambie el estado actual del canal.
4. WHEN se configure el modo espectador como deshabilitado, THEN Airi SHALL NOT ejecutar despertares proactivos ni transiciones de conversación activa de esta feature.
5. WHEN un temporizador se dispare mientras el canal está Despertando o mientras hay un turno de canal en curso, THEN Airi SHALL serializar o invalidar la transición para no competir con la finalización/publicación del turno.

### Requirement 5: Separación de retirada y desconexión global
**Objective:** Como operador, quiero que la retirada de una conversación no apague el bot, para que Airi siga disponible en el canal.

#### Acceptance Criteria
1. WHEN Airi se retire de una conversación activa, THEN Airi SHALL cambiar únicamente el estado conversacional del canal y SHALL NOT cerrar el cliente de Discord.
2. THE Airi SHALL mantener separadas la decisión de retirada conversacional y la acción global de desconexión existente.

### Requirement 6: Privacidad, observabilidad y verificabilidad

**Objective:** Como responsable del bot, quiero que el ciclo de vida sea testeable y observable sin persistir escucha temporal, para detectar fallos sin guardar contexto conversacional innecesario.

#### Acceptance Criteria
1. THE Airi SHALL mantener el estado activo, los temporizadores y el buffer pasivo en memoria y SHALL NOT escribirlos en el estado persistido del bot.
2. WHEN se registre una transición o un turno se omita por estado/temporizador, THEN la observabilidad existente SHALL identificar el estado, la transición o el motivo de omisión sin registrar contenido de mensajes.
3. THE Airi SHALL permitir pruebas deterministas del ciclo de vida mediante reloj y dependencias controlables.
4. THE test suite SHALL verificar el despertar por señales, el bypass de gating en modo Activo, la respuesta y silencio estructurados, la retirada del LLM, el timeout local, la iniciativa proactiva, fallos de generación/publicación y aislamiento entre canales.

### Requirement 7: Arranque, recuperación de pendientes y proactividad
**Objective:** Como operador, quiero que Airi recupere correctamente una conversación al conectarse, permanezca activa mientras haya interacción e inicie turnos espontáneos tras inactividad, sin duplicar respuestas ni ejecutar temporizadores obsoletos.

#### Acceptance Criteria
1. WHEN Airi se conecte a Discord y publique su embed de conexión, THEN Airi SHALL examinar el historial del canal para localizar el último mensaje humano que siga pendiente de atención, y el embed SHALL NOT computarse como actividad humana.
2. WHILE se seleccione el candidato de arranque, THE Airi SHALL excluir mensajes de bots, comandos, mensajes sin contenido y mensajes cuyos IDs consten como respondidos en el registro persistido de respuestas.
3. WHEN el candidato sea demasiado antiguo según `AIRI_SPECTATOR_PENDING_MAX_AGE_SECONDS`, THEN Airi SHALL NOT recuperarlo y SHALL entrar en Espectadora.
4. IF existe un candidato pendiente y reciente, THEN Airi SHALL responder únicamente a ese mensaje y SHALL entrar en Activa; IF no existe, THEN Airi SHALL entrar en Espectadora y SHALL NOT ejecutar la respuesta inicial y la proactividad como dos acciones del mismo arranque.
5. WHEN la generación o la publicación de la respuesta de arranque falle, THEN Airi SHALL NOT marcar el mensaje como respondido (invariante I3) y SHALL conservar la posibilidad de recuperación sin duplicar envíos.
6. WHEN un turno proactivo vaya a publicarse, THEN Airi SHALL revalidar que el canal sigue en Espectadora, que se mantiene la inactividad requerida, que no hay turno en curso y que no surgió actividad humana posterior que invalide el disparo (invariante I6).
7. THE Airi SHALL garantizar como máximo un turno en ejecución por canal (invariante I1) y SHALL impedir que tareas de temporizador obsoletas actúen con estado, generación o token desalineados (invariante I4).
8. THE registro de mensajes respondidos SHALL persistir en el estado del bot para que, tras un reinicio, un mensaje ya atendido no vuelva a ser candidato (invariante I2), y SHALL solo marcarse tras la publicación exitosa en Discord.
9. WHEN la publicación esté en estado incierto (confirmación perdida tras el envío), THEN la recuperación SHALL conciliar el registro de turnos antes de reintentar (T15) y SHALL reanudar respuestas confirmadas pendientes al arrancar.
10. THE Airi SHALL excluir del cómputo de actividad humana sus propios embeds de conexión/desconexión y los mensajes de otros bots (invariante I5), y SHALL aislar estado y temporizadores por canal (T21).

#### Configuración
| Variable | Responsabilidad |
| --- | --- |
| `AIRI_SPECTATOR_ACTIVE_IDLE_SECONDS` | Inactividad humana para retirar el canal de Activa a Espectadora. |
| `AIRI_SPECTATOR_PROACTIVE_IDLE_SECONDS` | Inactividad humana requerida para un turno espontáneo desde Espectadora. |
| `AIRI_SPECTATOR_PENDING_MAX_AGE_SECONDS` | Antigüedad máxima del pendiente recuperable en el arranque (por defecto 3600). |
| TTL del buffer pasivo (`AIRI_SPECTATOR_TTL_SECONDS`) | Vigencia del contexto escuchado pasivamente; no determina pendencia. |

#### Matriz de aceptación (T01–T22)
Arranque: T01 pendiente válido → respuesta dirigida; T02 último ya respondido → no repetir; T03 fuera del límite → no recuperar; T04 sin pendientes → Espectadora; T05 bot/comando → excluido; T06 varios pendientes → el último humano pendiente.
Estados y temporizadores: T07 retirada única al vencer; T08 actividad previa al vencimiento no retira; T09 proactivo único con ventana válida; T10 carrera mensaje/proactivo → un solo turno; T11 rearmes sucesivos → solo la tarea vigente actúa; T12 proactivo publicado → siguiente ciclo Activa.
Fallos y recuperación: T13 fallo de generación → no marcar respondido; T14 Discord rechaza → registrable y recuperable; T15 confirmación perdida → conciliar antes de reintentar; T16 reinicio en turno → sin doble respuesta; T17 desconexión → ninguna tarea obsoleta publica; T18 fallo de transición → nunca bloqueado en Despertando/Retirada.
Regresión e integración: T19 embed de conexión ≠ actividad humana; T20 embed de desconexión no reactiva; T21 aislamiento por canal; T22 buffer pasivo conserva contexto sin responder por mensaje. Cada escenario debe tener prueba automatizada o justificación explícita de verificación.
