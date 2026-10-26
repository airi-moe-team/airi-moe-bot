# Evaluación de interacción natural — fase 2

Este directorio conserva los artefactos de la evaluación A/B de `R7-R12`.
La suite automática **no** ejecuta el modo live: requiere el `llama-server`
local y se lanza de forma explícita.

## Artefactos

| Archivo | Contenido |
|---|---|
| `baseline-20261026.jsonl` | Captura anterior a los cambios de prompt (13 turnos). |
| `baseline-20261026-scored.jsonl` | Baseline con rúbrica manual. |
| `candidate-20261026-v7.jsonl` | Candidato intermedio con el limitador de acciones. |
| `candidate-20261026-v7-scored.jsonl` | Candidato v7 con rúbrica (57/70). |
| `candidate-20261026-v9.jsonl` | Candidato final con todas las correcciones. |
| `candidate-20261026-v9-scored.jsonl` | Candidato final con rúbrica (60/70). |

Los candidatos v2-v6 y v8 se conservan como evidencia de la variabilidad del
muestreo y de las iteraciones descartadas. No se usan para la decisión final.

## Comandos

```bash
# Captura live contra el endpoint configurado
python tools/interaction_eval.py --live \
  --out .kiro/specs/airi-interaccion-natural/eval/candidate.jsonl

# Comparación con baseline ya puntuado
python tools/interaction_eval.py --run \
  .kiro/specs/airi-interaccion-natural/eval/candidate-20261026-v9-scored.jsonl \
  --baseline .kiro/specs/airi-interaccion-natural/eval/baseline-20261026-scored.jsonl \
  --json
```

## Rúbrica por escenario

Puntuación 0-2 por criterio; máximo 10 por escenario y 70 por ejecución.

| Escenario | Baseline | Candidato v9 |
|---|---:|---:|
| Pregunta directa | 8 | 9 |
| Corrección | 5 | 9 |
| Saludo breve | 7 | 7 |
| Preferencia corregida | 4 | 9 |
| Desacuerdo | 5 | 7 |
| Charla casual | 8 | 9 |
| Despedida | 9 | 10 |
| **Total** | **46/70** | **60/70** |

La mejora agregada es **+14 puntos**. No hay regresiones críticas: los 13
turnos parsean, terminan con `finish_reason=stop`, no hay truncamientos,
fallos de esquema ni contradicciones de estado.

## Métricas observables

| Métrica | Baseline | Candidato v9 | Lectura |
|---|---:|---:|---|
| `gesture_density` | 0.154 | 0.308 | Regresión de calidad: más acotaciones, aunque sin apilarlas. |
| `stacked_gestures` | 0 | 0 | Sin acumulación de gestos en una respuesta. |
| `prefab_farewells` | 0 | 1 | Una fórmula de disponibilidad (`cuenta conmigo`). |
| `disproportionate_replies` | 1 | 4 | Respuestas largas para mensajes breves. |
| `question_only_replies` | 0 | 0 | Ninguna respuesta es solo una pregunta. |
| `critical_violations` | 0 | 0 | Sin fallos graves de formato o estado. |

La regresión de calidad no es crítica según `R12.8/R12.11`: no afecta a
coherencia, privacidad, estado ni formato. Se documenta para no ocultarla.

## Hallazgos cualitativos

- **Corrección:** el baseline evadía la pregunta y volvía a preguntar. El
  candidato reconoce el fallo, responde y no encadena otra pregunta.
- **Memoria:** el baseline mantenía el flan como vigente y luego inventaba otro
  postre. El candidato marca el flan como `superseded`, deja el tiramisú como
  `active` y lo usa al preguntarle de nuevo.
- **Desacuerdo:** el baseline no fijaba una postura clara. El candidato discrepa
  y argumenta, aunque en el segundo turno aún dice «no es que lo defienda» antes
  de defenderlo.
- **Saludo breve:** el candidato mejora la brevedad, pero a veces trata el nombre
  del interlocutor como si no lo conociera. Es un riesgo residual de continuidad.
- **Proporcionalidad:** el candidato sigue siendo más largo que el baseline en
  preguntas simples y en charla casual.

## Limitación de reproducibilidad

El modelo local (`Qwen3.5-9B-Q4_K_M`, temperatura `0.6`) no es determinista.
Las pasadas v7 (57/70), v8 (descartada por saludo y fórmulas prefabricadas) y v9
(60/70) comparten prompt y parámetros, pero varían en redacción y gestos. Por eso
la comparación usa una pasada baseline y una pasada candidata, conserva todos los
artefactos y no presenta la diferencia como un efecto exacto del prompt.

`airi-replay` sirve para reproducir contexto, parser y estado; **no** sustituye
esta evaluación, porque no regenera respuestas. Para regenerar hay que usar
`--live` o un runner equivalente. El modo live queda fuera de `pytest`.

## Aprobaciones

La evaluación no aprueba la spec. `requirements`, `design` y `tasks` siguen con
`approved: false` en `spec.json`; la validación humana es un paso separado.
