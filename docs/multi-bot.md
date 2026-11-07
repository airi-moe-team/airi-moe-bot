# Dos personajes en un canal

`bot-a`, `bot-b` y `coordinator` ejecutan la misma imagen y commit. Cada bot
tiene su cuenta Discord, LLM, perfil y volúmenes. El coordinador usa HTTP interno
y SQLite; no necesita un tercer LLM ni Redis. Ejecuta una réplica de cada servicio.

## Configuración

Necesitas Docker Engine con Compose v2, dos cuentas de bot con **Message Content
Intent** habilitado, permiso para leer el canal y su historial y enviar mensajes,
embeds y archivos, y dos endpoints Chat Completions disponibles. Los modelos y
servidores LLM no se instalan aquí.

1. Copia `config/compose.example.env` a `.env`, `config/bot-a.example.env` a
   `.env.bot-a` y `config/bot-b.example.env` a `.env.bot-b`. Si existen, conserva
   su contenido y añade los valores que falten en lugar de sobrescribirlos.
2. En `.env`, configura el canal, los dos **IDs de usuario de Discord** y dos
   tokens internos distintos y aleatorios de al menos 24 caracteres. Los tokens
   internos autentican los workers; no son los tokens de Discord.
3. En cada archivo de bot configura su token Discord, URL, proveedor, modelo y
   clave LLM. Configura `OWNER_ID` si necesitas los comandos de administración.
4. Personaliza `config/luna.json`. Su ID `luna` coincide con Compose.
   `config/airi.json` conserva el estilo del prompt original mediante
   `legacy_airi`; su biografía y familia se editan en los archivos de perfiles.
   Desactiva ese flag si también quieres reemplazar la base de personalidad.

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 coordinator bot-a bot-b
```

No publiques archivos `.env` ni la salida completa de `docker compose config`,
que puede mostrar secretos. Git y el contexto Docker excluyen los `.env` reales.

Dentro de Docker, `localhost` apunta al propio contenedor. Las plantillas usan
`host.docker.internal:8081` y `:8082` para LLM en el host; Compose añade
`host-gateway` en Linux. El servidor LLM debe escuchar en una interfaz accesible
desde Docker, con firewall y autenticación apropiados. Para APIs remotas usa su
URL HTTPS. La red del coordinador no publica puertos al exterior; los servicios
sí tienen salida hacia Discord y sus proveedores.

En un entorno con inspección TLS, el Dockerfile admite una CA mediante BuildKit:

```bash
docker build --secret id=proxy_ca,src=/ruta/paquete-ca.pem -t airi-multibot:local .
docker compose up -d --no-build
```

Para HTTPS en ejecución, monta la CA de solo lectura y configura `SSL_CERT_FILE`
en un override local. Conserva el proxy y amplía `NO_PROXY` con el coordinador,
loopback y destinos internos necesarios. No desactives TLS ni copies certificados
de sesión a la imagen.

## Turnos y aislamiento

### Historia familiar

Airi y Luna son hermanas. `config/family.json` es la fuente compartida de
padres, infancia y recuerdos familiares ficticios. Cada perfil apunta a ese
archivo mediante `family_file`, relativo al directorio del perfil, y define
su propia `sibling_perspective`. Sus personalidades, memorias de usuarios y datos
privados siguen separados. Airi es la hermana mayor y Luna la menor; sus edades
y la diferencia de años no están definidas.

Airi conserva su personalidad original con `legacy_airi`, pero su biografía
canónica se toma ahora del perfil y de la familia compartida; ya no es hija única.
Luna comparte el pasado familiar, sin heredar las experiencias personales de Airi
con Nerea o Gael. La aplicación asocia cada personaje con su ID de Discord para
que un usuario que use el nombre de una hermana no se confunda con ella.

Edita el archivo familiar para cambiar los hechos comunes y los perfiles para
cambiar sus opiniones sobre la otra hermana. Reinicia ambas instancias después
de modificar el canon. El Dockerfile incluye los tres archivos de configuración;
reconstruye la imagen si los editas. No se migran ni comparten recuerdos privados.

### Comandos y turnos

Los comandos comunes `!yo`, `!animo`, `!yo historia` y `!yo revertir <n>`
funcionan en ambas instancias. Los alias con nombre usan el ID estable del perfil:
Airi acepta `!identidad-airi` y `!animo-airi`; Luna acepta `!identidad-luna` y
`!animo-luna`. Los subcomandos `historia` y `revertir` también admiten el alias
de identidad del personaje. Cada instancia registra únicamente sus propios alias.
Por ejemplo, `@Luna !identidad-luna` consulta a Luna y `@Airi !yo` consulta a Airi.

- Una mención tiene prioridad sobre responder a un bot. Los comandos sin
  destinatario son de Airi. En mensajes generales se alterna la candidata: su
  propio LLM decide primero si conviene hablar. Si guarda silencio, no se
  consulta inmediatamente a la hermana por el mismo mensaje.
- Mencionar a ambos selecciona Airi y permite continuar con la hermana.
  Mencionar o responder a uno solo no activa al compañero.
- Una ronda permite hasta seis intervenciones entre ambas, incluida la primera.
  Cada continuación requiere otra decisión del LLM de la hermana seleccionada.
  Pueden terminar antes: no deben repetir ideas ni inventar preguntas para seguir.
  Dividir una respuesta en varios mensajes Discord no consume varias intervenciones.
- Se agrupan mensajes consecutivos del mismo usuario durante tres segundos.
  Nunca se mezclan autores en un turno de afinidad. Se esperan ocho segundos
  entre intervenciones de bots. Los intervalos son configurables.
- Un mensaje humano sustituye el trabajo pendiente y cancela borradores sin
  autorizar. Una publicación ya autorizada puede terminar antes del nuevo turno.
  La nueva evaluación puede decidir escuchar si las personas hablan entre ellas.
  También los mensajes sin texto interrumpen la continuación automática.
- Una cita pausa las intervenciones automáticas del compañero. Se permiten
  comandos explícitos de consulta, pero no iniciar otra cita en el mismo canal.
- Los botones reservan un turno antes de ejecutar su callback. Si hay otro
  turno, el usuario debe volver a pulsar: no se encolan interacciones que caducan.
- Los bots autorizados aportan contexto, pero no ejecutan comandos ni modifican
  afinidad, recuerdos o citas de humanos. Otros bots y webhooks se ignoran.

El contexto compartido contiene hasta 30 mensajes y 16.000 caracteres con autor
y tipo de participante. Los datos privados permanecen en los volúmenes de cada
bot. El límite del contexto no borra el registro histórico de disco: incluye las
bases y volúmenes en tu política de retención y backups.

### Iniciativas durante el silencio

Después de 30 minutos sin actividad conversacional, el coordinador puede ofrecer
a una hermana la oportunidad de iniciar. Alterna las candidatas independientemente
de la alternancia de mensajes humanos. La candidata puede decidir no hablar.

Solo se ofrecen oportunidades entre 09:00 (inclusive) y 23:00 (exclusive), hora
de Lima, sin citas, trabajo pendiente, envíos inciertos ni bots no disponibles.
El presupuesto es de tres iniciativas por día local y canal, compartido entre ambas.
Una iniciativa cuenta al confirmarse su primera publicación, no al decidir.
La pausa mínima de tres horas comienza cuando termina la ronda. Si se guarda
silencio o falla la decisión, se espera media hora antes de evaluar otra oportunidad.

Las rondas iniciadas antes de las 23:00 pueden terminar después respetando su
presupuesto. Una intervención humana termina la ronda espontánea y recibe su
propia evaluación. No se inicia para reclamar atención ni preguntar por qué se
fueron los usuarios. Las charlas espontáneas no crean usuarios ficticios ni
modifican afinidad o recuerdos privados de humanos.

SQLite conserva las rondas, los contadores diarios, las pausas y la alternancia.
El cambio de fecha se calcula en la zona configurada, también en horarios que
cruzan medianoche. Los mensajes recuperados de la bandeja conservan su fecha
original: no se tratan como actividad recién ocurrida. Al arrancar se concede
una espera de reevaluación antes de nuevas iniciativas y se cancelan decisiones
y continuaciones antiguas; no se recuperan oportunidades perdidas.

## Variables e interfaces

El modo individual sigue siendo el predeterminado: `AIRI_COORDINATED=0`.
Compose establece estas variables:

| Variable | Uso |
| --- | --- |
| `AIRI_COORDINATED` | Activa el worker y suspende las respuestas autónomas anteriores |
| `AIRI_BOT_ID` | Identificador estable `airi` o `luna` |
| `AIRI_PERSONA_FILE` | Perfil JSON validado antes de conectar Discord |
| `COORDINATOR_URL` | Dirección HTTP interna |
| `COORDINATOR_TOKEN` | Credencial exclusiva de esta instancia |
| `COORDINATOR_BOTS` | Mapa JSON de los dos identificadores a IDs Discord |
| `AIRI_DATA_DIR`, `AIRI_TRACE_DIR` | Volúmenes privados |

`airi coordinate` lee `CHANNEL_ID`, `COORDINATOR_BOTS`,
`COORDINATOR_TOKEN_AIRI`, `COORDINATOR_TOKEN_LUNA` y `COORDINATOR_DB`.
Los tres servicios usan el mismo mapa de identidades. Esta primera versión
gestiona un único `CHANNEL_ID`. El coordinador recibe estas variables desde
`.env` a través de Compose; los valores omitidos utilizan los predeterminados:

| Variable | Predeterminado |
| --- | --- |
| `COORDINATOR_DEBOUNCE` | `3` segundos |
| `COORDINATOR_PROACTIVE_ENABLED` | `1` |
| `COORDINATOR_IDLE_SECONDS` | `1800` |
| `COORDINATOR_PROACTIVE_COOLDOWN_SECONDS` | `10800` |
| `COORDINATOR_PROACTIVE_MAX_PER_DAY` | `3` |
| `COORDINATOR_PROACTIVE_RECHECK_SECONDS` | `1800` |
| `COORDINATOR_MAX_BOT_INTERVENTIONS` | `6` |
| `COORDINATOR_BOT_TURN_DELAY_SECONDS` | `8` |
| `COORDINATOR_TIMEZONE` | `America/Lima` |
| `COORDINATOR_PROACTIVE_START_HOUR` | `9` |
| `COORDINATOR_PROACTIVE_END_HOUR` | `23` |

Los intervalos de participación y presupuestos deben ser positivos. La zona debe
ser IANA válida; las horas deben estar entre 0 y 23 y ser distintas. Se admite un
horario que cruce medianoche. La imagen incluye `tzdata`. El nombre anterior
`COORDINATOR_REPLY_DELAY` sigue como alias: si también existe el nombre nuevo,
prevalece `COORDINATOR_BOT_TURN_DELAY_SECONDS`.

Para apagar solo las iniciativas durante la inactividad configura
`COORDINATOR_PROACTIVE_ENABLED=0`; la participación contextual en conversaciones
humanas sigue activa. Después de cambiar `.env`, ejecuta
`docker compose up -d --no-deps --force-recreate coordinator`; conserva el volumen.

La API usa `Authorization: Bearer <token-de-la-instancia>`:

| Ruta | Función |
| --- | --- |
| `POST /workers/register` | Registra identidad, disponibilidad y cita; devuelve trabajos inciertos |
| `POST /events` | Registra eventos públicos y deduplica sus IDs Discord |
| `POST /jobs/claim` | Espera hasta diez segundos por trabajo asignado |
| `POST /jobs/{id}/check` | Comprueba vigencia para cancelar generación obsoleta |
| `POST /jobs/{id}/ready` | Autoriza el borrador antes de confirmar efectos locales |
| `POST /jobs/{id}/sending` | Registra intención de enviar un bloque y su nonce |
| `POST /jobs/{id}/complete` | Confirma resultado, decisión, mensajes enviados y estado de cita |
| `POST /components/claim` | Reserva inmediata para un botón de cita |
| `GET /healthz`, `GET /readyz` | Comprueba servicio y almacenamiento |

Los eventos contienen `id`, `channel_id`, `author_id`, `name`, `kind` (`human`
o `bot`), `content`, `mentions`, `reply_author_id` y `timestamp` (epoch original).
Los trabajos identifican
instancia, revisión, ronda, mensajes de origen y vencimiento. Los conflictos
devuelven HTTP 409 y las credenciales incorrectas, HTTP 401.

Los trabajos `decision` incluyen `target_kind` (`human`, `peer` o `proactive`)
y contexto público. Se completan con `outcome: "decision"` y
`decision: {"participate": true/false, "reason_code": "..."}`. Los motivos
permitidos son `invitation`, `relevant`, `sibling`, `no_contribution`,
`humans_talking`, `repetition` y `error`. Una decisión no puede llamar a `ready`
ni enviar mensajes. Si queda obsoleta, se descarta sin generar una respuesta.
El LLM no puede modificar el bot seleccionado, horario o presupuesto. La decisión
usa la configuración LLM existente de esa instancia, incluido `REQUEST_TIMEOUT`;
no se añade un tercer modelo ni se desactiva su razonamiento configurado.

## Fallos y recuperación

Un timeout, salida inválida o fallo de decisión se interpreta como silencio, sin
mensajes de error al canal ni reintento inmediato. Los logs registran un código
de motivo y los identificadores de bot/ronda, sin la salida libre del modelo.

Sin coordinador, los bots suspenden respuestas y guardan eventos en su bandeja
SQLite local. Reintentan con espera creciente. Nunca pasan al modo independiente.
La supervisión cancela llamadas HTTP de generaciones obsoletas; el servidor LLM
podría tardar en detener su cálculo.

Los trabajos vencen a los 360 segundos. Los workers informan disponibilidad cada
15 segundos y deben registrarse ambos antes de procesar trabajo. El check de
salud del bot exige conexión reciente a Discord y al coordinador, sin envíos
inciertos propios. Docker muestra servicios no saludables, pero la política
`restart` solo reinicia procesos que salen; los cortes se manejan internamente.

Al reiniciar se cancelan generaciones anteriores. Una publicación que pudo
llegar a Discord queda `uncertain` y bloquea el canal. El worker consulta sus
recibos y el historial; solo reconcilia entregas identificables. No reenvía el
texto. No se garantiza entrega exactamente una vez entre Discord y SQLite.

Si los logs muestran `Publication requires manual review`, conserva un backup e
inspecciona el trabajo y los mensajes del bot. No borres la base para desbloquear.
Después de determinar el resultado, un operador puede llamar a
`POST /jobs/{id}/complete` con la credencial del bot:

- `{"outcome":"reconciled","sent":["ID_DISCORD"]}` para entrega confirmada.
- `{"outcome":"failed","sent":[]}` para cerrar sin reenviar.

Los efectos locales ya confirmados no se revierten automáticamente. Los logs de
coordinación incluyen canal, bot, trabajo, ronda, revisión y estado, sin tokens
ni prompts completos.

## Migración y reversión

Detén la instancia anterior y conserva una copia de seguridad fuera del checkout.
No ejecutes dos bots sobre los mismos datos. Copia el estado existente únicamente
al volumen **vacío** de Airi; Luna comienza con datos nuevos:

```bash
docker compose run --rm --no-deps --user root --entrypoint sh \
  --volume "$PWD/data:/migration:ro" bot-a -c \
  'test -z "$(ls -A /app/data)" && cp -a /migration/. /app/data/ && chown -R 10001:10001 /app/data'
```

Si el volumen tiene archivos, el comando se detiene. El bootstrap existente
valida el esquema de Airi. Conserva el backup hasta comprobar el arranque.

Para volver al bot individual conservando los volúmenes:

```bash
docker compose stop bot-a bot-b coordinator
docker compose run --rm --no-deps -e AIRI_COORDINATED=0 bot-a run
```

Resuelve envíos inciertos antes de cambiar de modo, porque el modo individual
utiliza su propia recuperación. No uses `docker compose down -v` si necesitas datos.

## Validación

```bash
uv sync --frozen
uv run --frozen pytest tests/
```

Las pruebas nuevas cubren enrutamiento, deduplicación, límites, interrupciones,
vencimientos, reinicios, perfiles, reloj controlado y el planificador de inactividad
con API HTTP real. También cubren dos workers con dobles de
Discord/LLM. Antes de usar un canal habitual, prueba con cuentas y LLM reales:
mención a cada bot, mensajes generales, interrupción humana, comando único,
citas y reinicios. Para probar inactividad sin esperar horas, usa intervalos
reducidos solo en un canal de pruebas y restaura después los valores normales.
La validación simulada no sustituye esa comprobación real.
