# Design Document — Búsqueda web conversacional

## 1. Objetivo

Que Airi decida cuándo comprobar algo en internet mediante tool calling nativo y lo cuente con su voz. La búsqueda deja de ser una regla léxica y pasa a ser una acción del modelo. El sistema no impone frases ni reescribe la respuesta.

## 2. Hallazgos del spike (llama.cpp 0.8.0-dev, Qwen3.5-9B, CPU)

- `tools` + `tool_choice: "auto"` funciona y devuelve `message.tool_calls` con `arguments` JSON.
- `tools` + `tool_choice: "required"` fuerza la llamada.
- `tool_choice` como objeto (`{"type":"function",...}`) no está soportado por este build; solo string.
- `tools` + `response_format` **no** conviven: el grammar JSON hace que el modelo escriba los argumentos como contenido y `finish_reason=stop`, sin `tool_calls`.
- Thinking + tools funciona; con CPU tarda ~16-32 s, con GPU será mucho menor.
- Un prompt de decisión explícito distingue bien precio actual (busca) de opinión (no busca). Con datos que el modelo cree conocer (p. ej. año de Matrix) puede no buscar; es coherente con "busca si duda", pero se medirá en evaluación.

## 3. Arquitectura

```
ConversationService.generate_turn
  ├─ WebSearchService.run(current_text, context)
  │    ├─ decide(): LLM chat_with_meta(tools=[buscar_web], tool_choice="auto")
  │    │    └─ parse_search_request(meta.tool_calls)
  │    ├─ notifier.send(aviso neutro)
  │    ├─ BraveSearchClient.search(query) -> WebSearchNotes | None
  │    └─ render_search_block(request, notes, failed) -> prompt_block | None
  ├─ _generate(..., web_context=prompt_block)
  └─ grounding heurístico -> solo traza
```

Dos llamadas al LLM cuando hay búsqueda; una de decisión (corta, sin schema) y una de generación (schema estricto, sin tools). Cuando no hay búsqueda, la decisión igualmente se ejecuta: no hay regex ni gate heurístico.

### 3.1 Elegibilidad por modo

La disponibilidad de la herramienta se separa de la decisión del modelo. Los turnos de respuesta normal, `spectator` (incluido el despertar por mención) y `active` pueden ejecutar la decisión nativa con `tool_choice="auto"`; esto no implica que todos busquen. Se mantiene la exclusión para citas y turnos proactivos sin una petición factual. `AIRI_WEB_SEARCH=0` continúa siendo el interruptor global. El replay offline mantiene `search=None` y `allow_web=False`: reproduce la respuesta guardada, pero no evalúa si el modelo habría elegido buscar.

## 4. Contratos

### 4.1 LLM

`LLMClient.chat_with_meta` acepta `tools: list[dict] | None` y `tool_choice: str | None`. `LLMMeta` incorpora `tool_calls: list[dict] | None`.

El adaptador normaliza cada tool call a:

```python
{"id": "...", "name": "buscar_web", "arguments": {"query": "...", "motivo": "..."}}
```

Reglas:
- `tools` + `schema` → `ValueError` (incompatibilidad conocida).
- `tools` + `stream` → `ValueError`.
- `tool_choice` solo string.
- Argumentos JSON inválidos → se descartan con warning y se registra en traza.

### 4.2 Búsqueda

```python
@dataclass(frozen=True)
class WebResult:
    title: str
    snippet: str

@dataclass(frozen=True)
class WebSearchNotes:
    results: tuple[WebResult, ...]

class WebSearchClient(Protocol):
    async def search(self, query: str) -> WebSearchNotes | None: ...
```

`None` = fallo de red/API. `WebSearchNotes(())` = sin resultados. El adaptador de Brave elimina URLs, ranking y numeración.

### 4.3 Decisión

```python
@dataclass(frozen=True)
class SearchRequest:
    query: str
    motivo: str
```

`WebSearchService` devuelve `WebSearchOutcome` con `requested`, `request`, `notes`, `failed`, `prompt_block`, latencias, `notice_sent`, `error`.

## 5. Prompt de decisión

System compacto con la identidad de Airi y criterios. Sin ejemplos de respuesta. Sentinela `NO_SEARCH` solo como texto de control. El `motivo` se escribe en primera persona y se inyecta en la generación final.

## 6. Bloque de notas

```
=== LO QUE ACABAS DE VER ===
Has buscado porque {motivo}.
Notas:
- {titulo}: {extracto}
...
Años mencionados en las notas: ...
=== CÓMO CONTARLO ===
- Integra la búsqueda como algo que acabas de hacer; no anuncies una consulta.
- Da el dato y reacciona con tu opinión.
- No inventes datos concretos que no estén en las notas.
- Si las notas no coinciden, dilo y muestra tu duda.
- Nada de URLs, listas de fuentes ni "según las fuentes".
```

Sin frases de respuesta entre comillas. La lista de años es un metadato neutro, no una frase de Airi.

## 7. Grounding

`reply_seems_grounded` se sigue calculando para `ev.web_grounded` y logs. No bloquea, no sustituye. `_acknowledges_search_failure` y `GROUNDED_FALLBACK_TEXT` se eliminan.

## 8. Observabilidad

Nuevos campos de `TurnEvent`: `web_requested`, `web_motivo`, `web_tool_backend`, `web_decision_ms`, `web_search_ms`, `web_grounded`, `web_notice_sent`, `web_error`, `web_note_years`. Se conservan `web_query`, `web_context`, `web_relevant` y `search_query` por compatibilidad.

## 9. Configuración

- `AIRI_WEB_SEARCH` (default `1`): apaga la herramienta sin tocar `allow_web`.
- `WEB_SEARCH_DECISION_MAX_TOKENS` (default 128; alias `SEARCH_QUERY_MAX_TOKENS`).
- `MAX_WEB_RESULTS` se mantiene.
- Requisito de servidor: `llama-server --jinja` y plantilla con soporte de tools.

## 10. Pruebas

- Unitarias: schema/tool, parseo de argumentos, notas sin URLs, hint de años, adaptador LLM (payload y tool_calls).
- Integración: tool call → una búsqueda → bloque en prompt; sin tool call → sin búsqueda; fallo → bloque de fallo; sin sustitución; modos normal/spectator/active elegibles; citas y proactivos sin petición factual excluidos; límite de una búsqueda.
- Replay: comprobar fidelidad determinista, sin tomarlo como evaluación de elegibilidad ni decisión web porque mantiene web deshabilitada.
- Regresión: transcripts actualizados al nuevo flujo.
- Evaluación semántica: 9 escenarios con juez, incluyendo hechos contextuales en spectator/active y abstención en opiniones, sin comparar frases literales.

### Resultado de evaluación live (Qwen3.5-9B, GPU, 2026-10-31)

- Decisión de búsqueda: 8/8 correctas (precision 1.0, recall 1.0): 6 búsquedas esperadas y 2 abstenciones correctas; sin falsos positivos.
- Juez semántico: 52/54 oportunidades (0.963). Es el mismo modelo y se toma como señal orientativa, no como evaluación independiente.
- La búsqueda vacía sí se invocó; Airi dijo que había buscado y no encontró notas oficiales, sin afirmar que carecía de acceso web.
- Se reforzó el prompt para tratar novedades recientes como información potencialmente desactualizada y se aclaró el estado vacío sin insertar una respuesta canónica.
- La evaluación inicial indicó que el juez estaba devolviendo solo rationale; se hicieron explícitas las claves y se activó schema estricto antes de recalcular.

## 11. Riesgos

- El modelo 9B puede no llamar en peticiones explícitas. Se mide; se corrige con prompt/modelo, no con regex.
- La llamada de decisión añade latencia. Se acota con contexto corto, `max_tokens` bajo y reasoning low.
- `tools` + `response_format` no son compatibles en el build probado; el diseño asume dos llamadas.
