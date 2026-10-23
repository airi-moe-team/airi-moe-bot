# Technology Stack

## Architecture

Arquitectura hexagonal (ports & adapters):

- `domain/`: lógica pura, sin I/O, sin Discord, sin HTTP.
- `ports/`: `Protocol` para LLM, búsqueda web, GIFs, notificador y repositorio.
- `services/`: orquestación usando solo ports; aquí vive el estado de aplicación.
- `adapters/`: implementaciones concretas (HTTP LLM, Brave, NekosBest, JSON, Discord).
- `discord_bot/`: capa fina de Discord (eventos, comandos, embeds, vistas).
- `observability/`: eventos y trazas por turno.

## Backend

- Python >= 3.11 (target ruff `py311`).
- `discord.py` para el cliente de Discord.
- `aiohttp` para LLM HTTP, búsqueda y GIFs.
- LLM local servido por llama.cpp en un endpoint compatible OpenAI (`LLM_BASE_URL`).
- Persistencia en JSON versionado (`data/state.json`), con backup, cuarentena y lock de instancia.
- Sin base de datos ni servicios externos obligatorios.

## Development Environment

- Entorno virtual `.venv` en la raíz.
- Instalación editable: `pip install -e .` (entry points `airi`, `airi-trace`, `airi-replay`).
- Configuración por `.env` (ver `.env.example`). Secretos nunca se versionan.
- Ruff con `line-length = 100`, reglas `E,F,W,I` (E501 ignorado).

## Common Commands

```bash
.venv/bin/python -m pytest tests/     # suite completa
.venv/bin/airi run                    # arrancar el bot
.venv/bin/airi-trace last             # última traza
.venv/bin/airi-replay <traza>.json    # reproducir un turno
.venv/bin/ruff check src tests        # lint
```

## Key Configuration

- `DISCORD_TOKEN`, `CHANNEL_ID` (canal autorizado), `OWNER_ID` opcional.
- `LLM_BASE_URL`, modelo y timeout de inferencia.
- `MAX_HISTORY_MESSAGES` (por defecto 12): límite de historial enviado al modelo.
- `DEBOUNCE_SECONDS`, `REPETITION_THRESHOLD` y demás constantes en `domain/constants.py`.
- `AIRI_TRACE_*` para retención y ruta de trazas.
- `AIRI_SHUTDOWN_REASON` para el motivo de desconexión.

## Testing

- `pytest` con `pythonpath = ["src"]`; sin dependencias extra, `asyncio.run()` en los tests.
- Fakes compartidos en `src/airi/testing/` (`FakeLLM`, `InMemoryRepository`, notificador, etc.).
- TDD obligatorio: test que falla (rojo), implementación mínima (verde), refactor.
- Todo bug nuevo debe convertirse en traza real → fixture en `tests/fixtures/traces/` → test.
