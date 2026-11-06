# Airi — Discord bot con LLM local (arquitectura hexagonal)

## Estructura

```text
.
├── data/                              (JSON de datos + traces/)
├── src/airi/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py                      (único config: Settings + env readers)
│   ├── logging_setup.py
│   ├── domain/                        (lógica pura: sin I/O, sin Discord, sin HTTP)
│   │   ├── constants.py               # env_int, env_float + CONSTANTES (afinidad, citas, diario)
│   │   ├── affinity.py                # niveles, deltas, decay, clamp y ranking
│   │   ├── relationships.py           # etapas afectivas, evidencia y propuestas
│   │   ├── dates.py                   # máquina de estados de la cita
│   │   ├── time_perception.py          # reloj local, franjas e intervalos
│   │   ├── history_tags.py             # vista de inferencia: identidad + cadencia
│   │   ├── gifts.py                   # catálogo y efectos de regalos
│   │   ├── diary.py                   # entradas, consultas, formato relativo
│   │   ├── memories.py                # alta/olvido de memorias sobre listas
│   │   ├── users.py                   # registro de actividad (puro)
│   │   ├── gifs.py                    # tipos, categorías y títulos de GIFs
│   │   ├── llm_output.py              # ModelOutput + parseo tolerante del LLM
│   │   ├── text_filters.py            # clean_reply, repeticiones del modelo
│   │   ├── grounding.py               # filtro anti-alucinación
│   │   ├── prompts.py                 # prompts + build_system_prompt(ctx)
│   │   ├── texts.py                   # textos narrativos (cita, confesión, regalos)
│   │   ├── web.py                     # marcadores léxicos heredados (no disparan búsquedas)
│   │   └── web_tool.py                # contrato y notas de la herramienta buscar_web
│   ├── ports/                         # Protocol (LLMClient, WebSearchClient, GifProvider,
│   │                               # Notifier, Repository)
│   ├── adapters/                      # http_llm (llama.cpp), brave_search, nekosbest,
│   │                               # json_repo + JSONRepository, discord_notifier
│   ├── services/                      # Orquestación (solo usan ports)
│   │   ├── state.py                   # AppState: datos + callbacks de persistencia
│   │   ├── conversation.py            # ConversationService.run_turn(...) → TurnResult
│   │   ├── web_search.py               # decisión nativa → Brave → notas conversacionales
│   │   └── date_service.py            # DateService: turno/cierre de citas
│   ├── discord_bot/                   # Capa Discord fina
│   │   ├── client.py                  # on_message: enrutar, debounce, delegar
│   │   ├── context.py                 # BotContext inyectado (+ trace_dir, last_traces)
│   │   ├── turn.py                    # run_user_turn: servicio → embeds/GIFs/vistas
│   │   ├── embeds.py                  # embeds y textos de ayuda
│   │   ├── commands/                  # un módulo por comando + registry
│   │   └── views/                     # botones de cita
│   ├── observability/                 # Trazas por turno + logging con correlation_id
│   │   ├── events.py                  # TurnEvent: campos + snapshots
│   │   ├── trace_store.py             # TraceStore: ring en memoria + disco atómico
│   │   ├── instrumentation.py         # turn_event/traced: eventos fuera de run_turn
│   │   ├── replay.py                  # `airi-replay <traza>.json`
│   │   ├── cli.py                     # `airi-trace last/show`
│   │   └── trace.py                   # re-export barrel (compatibilidad)
│   └── testing/                       🆕 (fakes compartidos con replay)
│       ├── fake_llm.py                # FakeLLM, llm_json
│       ├── in_memory_repo.py          # InMemoryRepository, make_state
│       ├── fake_doubles.py            # FakeSearch, FakeGif, FakeNotifier, FakeUser
│       └── __init__.py
├── tests/
│   ├── conftest.py
│   ├── __init__.py
│   ├── unit/                          # unidades puras (sin red ni Discord)
│   │   ├── test_events.py             # TurnEvent: serialización, aliases v1, recortes
│   │   ├── test_trace_store.py        # ring, disco atómico y fallos best-effort
│   │   ├── test_config.py             # Settings: AIRI_TRACE_* + fallback TRACE_*
│   │   ├── test_domain_edge_cases.py  # casos borde del dominio
│   │   ├── test_memories_domain.py    # alta/olvido de memorias
│   │   └── test_conversation_instrumented.py  # el evento sobrevive a errores
│   ├── integration/                   # ConversationService + citas + replay
│   │   ├── test_conversation_service.py
│   │   ├── test_date_flow.py
│   │   ├── test_replay.py
│   │   ├── test_debug_command.py
│   │   ├── test_observability.py
│   │   └── test_conversation_instrumented.py
│   ├── regression/                    # regresión por transcripts
│   │   └── test_transcripts_regression.py
│   ├── tools/                         # tests de herramientas
│   │   └── test_coverage_tool.py
│   ├── fakes/                         (solo re-exports de airi.testing)
│   └── fixtures/
│       ├── traces/                    (≥ 3 traces JSON)
│       └── transcripts/               (goldens sintéticos .jsonl)
├── tools/
│   ├── coverage.py
│   └── verify_migration.sh
├── pyproject.toml
├── README.md
├── MIGRATION_NOTES.md
├── .env / .env.example
└── .gitignore
```

## Búsqueda web conversacional

En los turnos que permiten búsqueda, Airi recibe la herramienta nativa
`buscar_web` y decide si la invoca. No hay regex ni `tool_choice` forzado para
disparar búsquedas. La decisión envía `query` y `motivo`; los resultados se
inyectan como notas breves, sin URLs ni ranking. El grounding heurístico se
conserva solo como telemetría y no reemplaza la respuesta.

El backend debe soportar OpenAI-style `tools` y ejecutar llama.cpp con
`--jinja`. En la versión probada, `tools` y `response_format` no deben enviarse
en la misma petición: Airi decide primero y genera su respuesta estructurada en
una segunda llamada. `AIRI_WEB_SEARCH=0` deshabilita la herramienta y
`WEB_SEARCH_DECISION_MAX_TOKENS` limita la llamada de decisión (el alias
histórico `SEARCH_QUERY_MAX_TOKENS` sigue aceptado).

Para evaluar la decisión y la voz sin depender de Brave:

```bash
.venv/bin/python tools/web_search_eval.py --live --out eval/web-search.jsonl --judge
.venv/bin/python tools/web_search_eval.py --run eval/web-search.jsonl --json
```

El harness usa ocho escenarios y resultados controlados; `--judge` añade una
revisión semántica local (llamadas extra al LLM). Los registros distinguen
precisión/recall de búsqueda y criterios de síntesis; las frases exactas no son
criterio. El endpoint CPU puede seleccionarse con `--base-url` sin modificar la
configuración de producción.

## Replay de trazas

`airi-replay <traza.json>` es determinista por defecto: reutiliza la respuesta
guardada, no crea clientes externos y reporta qué etapas quedan sin verificar.
Los resultados con `coverage: "partial"` no deben interpretarse como validación
completa.

La captura de búsqueda está apagada por defecto. Para habilitarla explícitamente
en los turnos que se quieran investigar, configura un directorio local privado:

```bash
AIRI_TRACE_WEB_CAPTURE_DIR=./private-web-captures .venv/bin/airi run
```

Los sidecars contienen consultas y snippets potencialmente sensibles; son JSON
locales con permisos `0600`, no se sobrescriben y deben excluirse del control de
versiones y eliminarse según la política local de retención. Las trazas
principales redactan el contenido web. Un sidecar se vincula a su traza mediante
`correlation_id`.

Modos explícitos:

```bash
# Seguro y determinista (predeterminado)
.venv/bin/airi-replay traces/2026-11-02/<correlation_id>.json

# Inferencia nueva, búsqueda web desactivada
.venv/bin/airi-replay traces/2026-11-02/<correlation_id>.json --live

# Inferencia nueva con búsqueda limitada al sidecar local; no usa Internet
.venv/bin/airi-replay traces/2026-11-02/<correlation_id>.json \
  --behavioral --capture ./private-web-captures/<correlation_id>.web-capture.json

# Solo si también se autoriza explícitamente el acceso web real
BRAVE_API_KEY=... .venv/bin/airi-replay traces/2026-11-02/<correlation_id>.json \
  --live --web-live

# Contexto de tarea privado, suministrado lateralmente y no persistido en la traza
.venv/bin/airi-replay traces/2026-11-02/<correlation_id>.json \
  --live --task-context ./private-task-context.json
```

`--web-live` requiere `--live` y `BRAVE_API_KEY`; no es un permiso implícito de
`--live`. `--behavioral` exige `--capture` válido y no tiene fallback a red.
Los estados `captured_empty`, `capture_missing` y `capture_mismatch` son
diferentes: una captura vacía válida no es lo mismo que carecer de captura o que
el modelo haya pedido otra consulta. Las divergencias de replay salen con código
1; los errores de ejecución con código 2. El fixture JSON de tarea acepta
`goal`, `constraints`, `progress` y `next_step`; trátalo como contenido privado.

## Reglas

- `domain/` no importa `discord`, `aiohttp` ni hace I/O de ficheros.
- Los servicios orquestan con `ports`; nunca con `adapters` directamente.
- `src/airi/__main__.py` construye `AppState` desde sus globales (`build_app_state()`) y
  los servicios vía `build_conversation_service()` + `DateService`.
- Los tests usan `asyncio.run()` (sin dependencias extra).
- **Todo bug nuevo se convierte en:** un TurnEvent real → un .json en `tests/fixtures/traces/` → un test automático.

## Ejecutar tests

```bash
.venv/bin/python -m pytest tests/
```

Estado actual: **299 tests** en 4 carpetas (unit, integration, regression, tools).

## Ejecutar el bot

El bot se ejecuta como aplicación instalable con `pip install -e .`:

```bash
pip install -e .                 # instala entry points: airi, airi-trace, airi-replay
.venv/bin/airi run               # inicia el bot (necesita .env con DISCORD_TOKEN y CHANNEL_ID)
```

Alternativamente, si no quieres instalar el paquete:

```bash
PYTHONPATH=src .venv/bin/python -m airi run
```

Ambos métodos requieren un archivo `.env` con las variables de entorno:
- `DISCORD_TOKEN`: token del bot de Discord
- `CHANNEL_ID`: ID del canal autorizado
- `LLM_PROVIDER`: perfil del proveedor (`llama`, `openai` u `openai-compatible`)
- `LLM_BASE_URL`: URL base del proveedor (default: http://127.0.0.1:7000)
- `LLM_THINKING_MODE`: preset de razonamiento (`auto`, `low`, `medium`, `high`; default: `auto`). Los presets son cerrados: `low=256`, `medium=1.024`, `high=4.096` tokens; `auto` usa el preset low en turnos rápidos y el default del servidor en turnos normales. No hay variables de entorno para cambiar esos valores ni la reserva fija de 512 tokens de salida. Un modo desconocido —incluidos `on` y `off`— advierte y vuelve a `auto`. Con `LLM_PROVIDER=llama`, los presupuestos se envían por petición mediante `thinking_budget_tokens`; dependen de la versión/template y son topes, no garantías de calidad. Si el servidor se inició con `--reasoning-budget`, puede prevalecer su presupuesto global. Las reparaciones y reflexiones estructuradas usan el preset low. Ninguna llamada apaga reasoning.
- `DATA_DIR`: directorio de datos (default: data)
- `TRACE_DIR`: directorio de trazas (opcional)
- `OWNER_ID`: ID del dueño del bot (opcional)
- `AIRI_TIME_CONTEXT`: percepción temporal en el prompt e historial (`1`, default; `0` desactiva para A/B o rollback)
- `AIRI_TIMEZONE`: zona horaria IANA opcional (p. ej. `Europe/Madrid`); vacío usa la zona del sistema
- `AIRI_CONVERSATION_REVIEW`: revisa coherencia del borrador con el hilo antes de publicar (`1`, default; `0` desactiva la llamada de revisión)

### Percepción temporal

Airi recibe la fecha, hora local y franja del día, el tiempo desde la última
interacción, el hueco de la sesión anterior y marcas temporales por mensaje. Las
marcas se calculan para cada prompt y no se guardan en el historial; los mensajes
nuevos conservan solo su epoch. Para huecos de una hora o más, la marca incluye el
día local real (`[hoy 05:49]`, `[ayer 23:10]`, `[30/10 22:15]`) y así Airi no tiene
que deducir la fecha a partir de un `hace N h` ambiguo. La hora exacta se incluye
como contexto para responder preguntas directas, pero el prompt le pide a Airi no
recitarla espontáneamente.

Además, Airi infiere el horario habitual de cada persona con las horas locales de
sus sesiones de actividad (una muestra por sesión, separadas al menos 30 minutos,
con un máximo de 60 por usuario). Si hay al menos cuatro sesiones y las horas
están concentradas, el prompt indica la hora habitual y si la persona llega antes,
dentro o más tarde de lo habitual. Con pocas muestras u horarios dispersos no se
declara ningún patrón.

El valor por defecto usa la zona del sistema operativo. En contenedores suele ser
UTC: fija `TZ=Europe/Madrid` o `AIRI_TIMEZONE=Europe/Madrid` si quieres hora de
Madrid. Al iniciar, el log informa la zona efectiva y su origen. Para revertir
sin desplegar código, configura `AIRI_TIME_CONTEXT=0`.

La comparación controlada usa los mismos instantes para baseline y candidato:

```bash
python tools/interaction_eval.py --live --scenario-set temporal \
  --time-context off --out /tmp/opencode/airi-time-baseline.jsonl
python tools/interaction_eval.py --live --scenario-set temporal \
  --time-context on --out /tmp/opencode/airi-time-candidate.jsonl \
  --baseline /tmp/opencode/airi-time-baseline.jsonl
```

La suite temporal cubre madrugada, mañana, tarde, noche, reaparición tras dos
minutos y tres días, e iniciativa proactiva nocturna. El resumen indica respuestas
no evaluables si no hay hora en la traza; no las cuenta como éxito.

## Naturalidad de la conversación

Tres mecanismos sostienen el tono (ver `src/airi/domain/prompts.py`):

1. **Respuestas proporcionadas.** El prompt obliga a responder en proporción al
   mensaje (un saludo no es un monólogo, un tema serio no es una broma), a usar
   acciones narrativas solo cuando aportan algo y a no terminar siempre con una
   pregunta.
2. **Citas conversacionales.** Durante una cita NO hay botones por turno: la
   conversación fluye sola. Airi puede hacer **una única pregunta decisiva**
   (`date_question` en el contrato JSON) con 2-3 alternativas, solo si el
   momento la justifica; al responder se tira el dado (`up_chance`) y se aplica
   el swing de afinidad (hasta ±25). No hay pregunta de reserva ni turno
   forzado: la cita puede terminar sin pregunta.
3. **Aislamiento por interlocutor.** El historial que se envía al modelo lleva
   una etiqueta por intervención (`[speaker=Nombre|affinity=N|level=Nivel]`)
   para que Airi no arrastre el tono ni el vínculo de otra persona. La
   afinidad visible es, por defecto, solo la de quien le habla
   (`AFFINITY_VIEW_SCOPE=recipient`; `all` muestra la de cada uno).

## Relación natural basada en evidencia

- La **afinidad** mide cercanía y elegibilidad (citas, propuestas); no cambia
  por sí sola la etapa afectiva ni confirma una pareja.
- Cada usuario tiene una **etapa romántica** (`none`, `curiosity`, `interest`,
  `enamored`) en `world.relationships`. Solo avanza un paso por turno, con un
  motivo y referencias a interacciones recuperables del mismo usuario. El
  turno actual se ofrece como `turn:<channel>:<message>` y las transiciones
  previas como `ev:<id>`; esas referencias no se pueden inventar.
- Una **propuesta de pareja** solo es válida si la etapa `enamored` ya existía
  antes del turno. Queda pendiente hasta que la persona destinataria acepte de
  forma explícita; un rechazo cierra la propuesta y una respuesta ambigua no
  cambia nada. Al aceptar se confirma `winner_id` y se aplica la monogamia.
- Los cambios afectivos, la propuesta y `winner_id` se confirman en la misma
  transacción del turno; si el commit falla, todo se revierte.

## Debugging y trazas

Cada turno genera un `TurnEvent` con un `correlation_id` (12 hex) que viaja en
los logs (`[cid=...]`) y en la traza. El evento guarda los **snapshots del
estado previos al turno** (afinidad, mundo, memorias, diario y cita), el prompt
enviado, la respuesta cruda del modelo, el parseo, la afinidad y las citas, de
modo que el turno se puede reproducir sin Discord ni red.

`TraceStore` mantiene siempre un ring en memoria (los últimos `N` turnos) y, si
hay directorio, persiste cada evento de forma atómica (`<dir>/<día>/<cid>.json`).
Ninguna operación lanza excepciones: un fallo de disco se registra y el turno
continúa.

Además de los turnos de conversación, se instrumentan los demás flujos que no
pasan por `run_turn`: los comandos (`kind="command"`), `!regalo`
(`kind="gift"`), la elección de escena al iniciar una cita
(`kind="scene_select"`) y las acciones de cita (`kind="date_action"`). Todos
comparten el mismo `TraceStore`.

Los ajustes se leen del entorno con `airi.config.Settings` (stdlib, sin
`pydantic-settings`): se prefiere el prefijo `AIRI_` y se acepta el nombre
histórico (`AIRI_TRACE_DIR` → `TRACE_DIR`).

```bash
# Guardar trazas en disco (vacío = solo ring en memoria)
TRACE_DIR=./traces          # o AIRI_TRACE_DIR
# Tamaño del ring en memoria (turnos inspeccionables con `!debug`)
TRACE_KEEP_LAST=500         # o AIRI_TRACE_KEEP_LAST
# Motivo que deja Airi al apagar el bot con Ctrl+C
AIRI_SHUTDOWN_REASON="se fue a dormir"
```

### Modo espectador (escucha pasiva)

Con estas variables Airi lee el canal sin responder a todo: solo despierta ante
mención/respuesta/nombre, un mensaje que toca un gusto de su perfil, o un autor
con afinidad suficiente. Interés y afinidad son señales independientes; la
tirada fallida NO consume el cooldown (ese se arma solo al publicar con éxito).

```bash
AIRI_SPECTATOR_ENABLED=0           # apagado por defecto; 1 = activar
AIRI_SPECTATOR_BUFFER_MAX=20       # entradas máximas por canal
AIRI_SPECTATOR_TTL_SECONDS=1800    # caducidad de lo leído como espectadora
AIRI_SPECTATOR_AFFINITY_POINTS=20  # umbral de afinidad por autor
AIRI_SPECTATOR_PROB_TOPIC=0.55     # probabilidad cuando hay tema
AIRI_SPECTATOR_PROB_AFFINITY=0.35  # probabilidad cuando hay afinidad
AIRI_SPECTATOR_COOLDOWN_SECONDS=300
AIRI_SPECTATOR_SNAPSHOT_MAX=12     # ventana máxima del snapshot efímero
AIRI_SPECTATOR_HANDOFF_SECONDS=180 # ventana para contestar a la pregunta de Airi
AIRI_SPECTATOR_ACTIVE_IDLE_SECONDS=300 # ventana activa al conectar y tras cada mensaje
# Perfil estable de gustos (JSON). Si está definida y es válida, prevalece
# sobre lo persistido y sobre cualquier cambio posterior de identidad.
AIRI_PROFILE='{"loves":["videojuegos","ramen"],"dislikes":["grosero"],"favorite_food":"postres y dulces","favorite_flower":"las rosas"}'
```

El **handoff**: tras una intervención espontánea (que pudo dejar una pregunta),
el interlocutor tiene una ventana (`HANDOFF_SECONDS`) para responder una vez
sin cooldown; después vuelve el cooldown normal. El mensaje disparador y el
snapshot se consumen del buffer al publicar, así el tema no queda latente.

Al **conectar** con el modo espectador activado, el canal arranca en Activa
durante `AIRI_SPECTATOR_ACTIVE_IDLE_SECONDS` (300 s por defecto) aunque no haya
nadie a quien responder. Cada mensaje humano reinicia esa ventana. Si hay un
mensaje pendiente, Airi responde solo a ese y también queda en Activa. Cuando la
ventana vence sin actividad, vuelve a Espectadora.

- `!debug ultimo [n]` (solo dueño): resumen de los últimos `n` eventos del
  ring (def. 1, máx. 20) — incluye comandos, regalos y citas.
- `!debug id <cid>` (solo dueño): envía el JSON del evento con ese
  `correlation_id` como adjunto (lo busca en el ring y, si no, en `TRACE_DIR`).
- `!debug errores` (solo dueño): lista los eventos recientes con errores.
- `!debug clear` (solo dueño): vacía el ring en memoria (no toca el disco).
- `!debug turno` / `!debug trace` (solo dueño): resumen / JSON de tu último
  turno con Airi.

### CLI de trazas

```bash
airi-trace last 10                    # resumen de los últimos 10 eventos
airi-trace show <cid>                 # JSON completo de un correlation_id
airi-trace repairs                    # agrupa reparaciones por motivo e indica sus trazas
```

### Reproducir una traza

```bash
airi-replay ./traces/2026-10-14/<cid>.json
# exit 0 = la reproducción coincide; exit 1 = diverge o no es reproducible
# El replay reutiliza la respuesta guardada y mantiene búsqueda/notificaciones externas
# deshabilitadas; verifica fidelidad, no si Airi habría decidido buscar en vivo.

airi-replay --emit-test ./traces/.../<cid>.json
# genera tests/integration/test_regression_<cid>.py desde la traza
```

### Comparar variantes del system prompt

Con llama-server disponible, el benchmark permite seleccionar `auto`, `low`,
`medium` o `high` mediante `LLM_THINKING_MODE`; el cliente registra el
presupuesto enviado por llamada por separado de los tokens/evidencia de reasoning
devueltos, ya que el backend puede ignorar el presupuesto por petición. El benchmark ejecuta cinco
pares secuenciales por defecto, alterna su orden y guarda/imprime solo métricas
y checks (no el prompt ni las respuestas). El benchmark usa streaming para
medir TTFT; el camino normal del bot sigue sin streaming:

```bash
LLM_THINKING_MODE=auto airi-prompt-benchmark \
  ./traces/2026-10-26/722f84144006.json --pairs 5 \
  --metrics-url http://127.0.0.1:7000/metrics \
  --out /tmp/opencode/prompt-benchmark.json
```

Para timings internos y snapshots, el operador debe iniciar manualmente
llama-server con `--perf --metrics`; el benchmark nunca reinicia ni reconfigura
el servidor. Comprueba primero que esas opciones existan con el `--help` de tu
build. `--expert-stats` no reemplaza timings de inferencia. Los deltas de
Prometheus se etiquetan como agregados, pues puede haber otras peticiones al
servidor.

Añade `--review` para valorar localmente relevancia, coherencia, proporcionalidad
y reglas esenciales. En ese modo el texto se muestra en terminal durante la
revisión, pero no se guarda en el reporte. Sin esa revisión semántica el informe
deja `candidate_acceptable` pendiente. `ttft_ms` mide el primer delta generado y
`first_content_ms` el primer texto visible; ambos pueden diferir si el servidor
separa `reasoning_content` de `content`.

Cada muestra incluye además `call_count`, `repair_ms`, `call_purposes` y el
detalle `calls`: una entrada por invocación al modelo con propósito y duración.
Así se distingue la respuesta visible del coste de las reparaciones, sin guardar
prompt, historial, contenido ni reasoning. En streaming el cliente pide `usage`
al servidor (`stream_options`), de modo que `completion_tokens` deja de ser nulo;
`reasoning_deltas` es un proxy por fragmento SSE, no un conteo exacto.
`server_timings` y `ttft_ms` describen la primera llamada; `llm_ms` incluye las
reparaciones.

## Regresión y cobertura (Fase 6)

### Transcripts

`tests/fixtures/transcripts/*.jsonl` guardan conversaciones completas: por
turno, el texto del usuario y la respuesta CRUDA del modelo. El runner
(`tests/regression/test_transcripts_regression.py`) las reinyecta con `FakeLLM` a través
de `ConversationService`/`DateService` y compara contra las expectativas
grabadas en el propio fichero (patrón auto-golden):

- Un transcript nuevo se ejecuta, graba sus expectativas y se marca `skipped`;
  la siguiente ejecución ya verifica.
- Si cambias comportamiento a propósito, regenera los goldens:

```bash
RECORD_TRANSCRIPTS=1 .venv/bin/python -m pytest tests/regression/test_transcripts_regression.py
```

Transcripts incluidos: conversación normal, subida de nivel (Amiga) con
reflexión de diario, JSON inválido, delta sin motivo, grounding rechazado,
respuesta duplicada (skip), cita con crisis y recuperación, y cita fallida.

> Nota: con los snapshots, una traza de producción ya es en sí misma un
> transcript reproducible (inputs + prompt + respuesta cruda + estado previo),
> por lo que no se añadió un convertidor traza→transcript. Los
> `tests/fixtures/transcripts/*.jsonl` se mantienen como goldens sintéticos
> para caminos no observados en producción.

### Cobertura

`coverage.py`/`pytest-cov` no están instalados en este entorno sin red, así
que `tools/coverage.py` mide la cobertura de líneas con `sys.settrace`
(stdlib) durante la suite:

```bash
.venv/bin/python tools/coverage.py              # objetivos: domain >= 90%, services >= 70%
.venv/bin/python tools/coverage.py --missing    # + líneas sin cubrir
```

Estado actual: `domain/` ~97%, `services/` ~99%.
