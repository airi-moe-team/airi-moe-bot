# Project Structure

## Root Directory Organization

```text
data/                  Estado persistido y trazas (runtime, no versionar datos sensibles)
src/airi/              Código de la aplicación (src layout)
tests/                 unit, integration, regression, tools, fakes, fixtures
tools/                 utilidades (cobertura, verificación de migración)
docs/                  Documentación y auditorías
.kiro/                 Steering y specs SDD
pyproject.toml         Metadatos, entry points, pytest y ruff
README.md              Estructura y reglas de arquitectura
```

## Subdirectory Structures

### `src/airi/domain/`
Lógica pura y constantes. Archivos clave: `affinity.py` (niveles/deltas/decay),
`relationships.py`, `dates.py`, `prompts.py` (prompt de sistema y secciones dinámicas),
`llm_output.py` (parseo tolerante + validación), `history_tags.py`, `text_filters.py`,
`turn_guard.py`, `state_schema.py`, `constants.py`.

### `src/airi/ports/` y `src/airi/adapters/`
Contratos `Protocol` y sus implementaciones. Los servicios no importan adapters.

### `src/airi/services/`
Orquestación y estado: `state.py` (`AppState` con historiales, afinidad, memorias),
`conversation.py` (`ConversationService.run_turn` → `TurnResult`), `date_service.py`,
`persistence.py`, `bootstrap.py`, `migration.py`, `turn_coordinator.py`,
`channel_queue.py`, `turn_journal.py`, `relationships.py`, `self_service.py`.

### `src/airi/discord_bot/`
`client.py` (evento `on_message`, routing, debounce, dispatch), `turn.py`
(`run_user_turn`: servicio → embeds/GIFs/vistas), `context.py` (`BotContext` inyectado),
`commands/` (un módulo por comando + registry), `views/`.

### `src/airi/observability/`
`events.py` (`TurnEvent`), `trace_store.py`, `instrumentation.py`, `replay.py`, `cli.py`.

### `tests/`
- `unit/`: dominio puro y componentes aislados.
- `integration/`: `ConversationService`, citas, replay, comandos, persistencia.
- `regression/`: transcripts golden.
- `fixtures/`: trazas JSON y transcripts sintéticos.

## Code Organization Patterns

- Dependencias siempre hacia dentro: `discord_bot`/`adapters` → `services` → `domain`.
- El estado mutable vive en `AppState`; los servicios reciben `ctx`/`state`, no globals.
- Los callbacks de persistencia se inyectan; no se escribe a disco desde el dominio.
- Los turnos se serializan por canal mediante dispatcher/cola; respetar ese orden.
- Los comandos se registran en `commands/registry.py` y reciben `BotContext`.

## File Naming Conventions

- Módulos y funciones en `snake_case`; clases en `PascalCase`.
- Tests `test_<área>.py`; fixtures de traza con id hexadecimal.
- Constantes en mayúsculas, centralizadas en `domain/constants.py` cuando son configurables.

## Import Organization

- Imports estándar, terceros y locales separados (ruff `I`).
- Sin imports de `discord`/`aiohttp` dentro de `domain/`.
- Evitar imports pesados en tiempo de módulo cuando se pueden hacer locales (patrón usado
  en `client.py` para glue de citas).

## Key Architectural Principles

- Naturalidad antes que funcionalidad: ninguna mecánica debe forzar conversación.
- Filtros locales (regex/estado) antes de gastar una llamada al LLM.
- Determinismo y testeabilidad: umbrales y probabilidades inyectables, sin azar oculto.
- Privacidad por defecto: no enviar DMs a terceros sin consentimiento explícito.
- Todo cambio de comportamiento debe ser observable en `TurnEvent`/trazas.
