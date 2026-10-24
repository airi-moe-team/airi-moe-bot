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
