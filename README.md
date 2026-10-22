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
│   │   ├── affinity.py                # niveles, deltas, decay, clamp, coronación, ranking
│   │   ├── dates.py                   # máquina de estados de la cita
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
│   │   └── web.py                     # detección de mensajes que piden búsqueda web
│   ├── ports/                         # Protocol (LLMClient, WebSearchClient, GifProvider,
│   │                               # Notifier, Repository)
│   ├── adapters/                      # http_llm (llama.cpp), brave_search, nekosbest,
│   │                               # json_repo + JSONRepository, discord_notifier
│   ├── services/                      # Orquestación (solo usan ports)
│   │   ├── state.py                   # AppState: datos + callbacks de persistencia
│   │   ├── conversation.py            # ConversationService.run_turn(...) → TurnResult
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
- `LLAMA_URL`: URL del servidor llama.cpp (default: http://127.0.0.1:8081)
- `DATA_DIR`: directorio de datos (default: data)
- `TRACE_DIR`: directorio de trazas (opcional)
- `OWNER_ID`: ID del dueño del bot (opcional)

## Naturalidad de la conversación

Tres mecanismos sostienen el tono (ver `src/airi/domain/prompts.py`):

1. **Respuestas proporcionadas.** El prompt obliga a responder en proporción al
   mensaje (un saludo no es un monólogo, un tema serio no es una broma), a usar
   acciones narrativas solo cuando aportan algo y a no terminar siempre con una
   pregunta.
2. **Citas conversacionales.** Durante una cita NO hay botones por turno: la
   conversación fluye sola. Airi dispone de **una única pregunta decisiva**
   (`date_question` en el contrato JSON) con 2-3 alternativas; al responder se
   tira el dado (`up_chance`) y se aplica el swing de afinidad (hasta ±25). Si
   la IA no llega a preguntar, se lanza la pregunta de reserva en el turno
   `DATE_QUESTION_FORCE_TURN`.
3. **Aislamiento por interlocutor.** El historial que se envía al modelo lleva
   una etiqueta por intervención (`[speaker=Nombre|affinity=N|level=Nivel]`)
   para que Airi no arrastre el tono ni el vínculo de otra persona. La
   afinidad visible es, por defecto, solo la de quien le habla
   (`AFFINITY_VIEW_SCOPE=recipient`; `all` muestra la de cada uno).

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
# Omitir la respuesta cruda del modelo (ahorra disco, pero el turno
# deja de ser reproducible)
TRACE_KEEP_RAW=1
# Tamaño del ring en memoria (turnos inspeccionables con `!debug`)
TRACE_KEEP_LAST=500         # o AIRI_TRACE_KEEP_LAST
```

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
```

### Reproducir una traza

```bash
airi-replay ./traces/2026-10-14/<cid>.json
# exit 0 = la reproducción coincide; exit 1 = diverge o no es reproducible

airi-replay --emit-test ./traces/.../<cid>.json
# genera tests/integration/test_regression_<cid>.py desde la traza
```

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
