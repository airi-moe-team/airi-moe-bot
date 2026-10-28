# Cierre de pendientes de Airi — 2026-10-27

Evaluaciones locales exploratorias; no cambian el prompt predeterminado ni la
configuración de producción.

## Replay de la traza `c35bd84149ac`

- Archivo: `traces/2026-10-27/c35bd84149ac.json`
- Comando: `airi-replay traces/2026-10-27/c35bd84149ac.json`
- Resultado: reproducible y coincidente; todos los checks del replay pasaron,
  incluidos `session_schema=true` y `stay_active=true`.
- Modo: `kind=active`. Es un turno de sesión; `stay_active=true` es válido y
  corresponde a `SESSION_RESPONSE_SCHEMA`, no es una clave extra inválida.
- La llamada primaria acabó con `finish_reason=length`, 4096 completion tokens y
  thinking efectivo. La reparación acabó en `stop` con 294 completion tokens.
  La latencia combinada registrada fue 84.512 ms.

## A/B de los seis escenarios de identidad

Artefactos:

- `identity-baseline-v2-20261027.jsonl`
- `identity-candidate-v2-20261027.jsonl`
- `identity-comparison-v2-20261027.json`

Ambos brazos usaron el modelo y la configuración live del entorno, estado nuevo
por escenario y contrato normal idéntico. Los resultados agregados fueron:

| Métrica | Prompt actual | Candidata |
|---|---:|---:|
| Densidad de gestos | 0,571 | 0,429 |
| Respuestas desproporcionadas | 2 | 3 |
| Fallos de schema | 0 | 0 |
| Turnos con truncamiento primario | 1 | 1 |

La candidata muestra opiniones más específicas sobre personajes imperfectos,
respeto y relaciones graduales; la respuesta al desacuerdo fue más distintiva y
la charla casual más proporcionada. No resuelve del todo la repetición: vuelve a
mencionar la falta de cuerpo/infancia en varias respuestas y sigue cerrando con
preguntas con frecuencia. La métrica de proporcionalidad empeoró en una respuesta.

Valoración cualitativa del agente (0-2 por criterio; orientativa, no revisión
humana formal):

| Criterio | Prompt actual | Candidata |
|---|---:|---:|
| Repetición | 1 | 1 |
| Perspectiva propia | 1 | 2 |
| Naturalidad | 1 | 1 |
| Respuesta directa | 1 | 2 |
| Schema/contrato | 2 | 2 |
| **Total provisional** | **6/10** | **8/10** |

**Decisión:** mantener la candidata experimental; no promoverla a producción aún.
La revisión semántica aquí es cualitativa del agente, no una puntuación humana
formal. La comparación automática no observó una regresión crítica diferencial,
pero ambas variantes tuvieron un turno truncado que necesitó reparación.

## Perfiles de thinking y límite de salida sobre la traza

Artefactos:

- `trace-c35-profile-off-1200-8pairs-20261027.json` — 6 pares completos.
- `trace-c35-profile-off-800-7pairs-20261027.json` — 5 pares completos.
- `trace-c35-profile-on-1200-10pairs-20261027.json` — 7 pares completos.

Todos usaron el modo `active`/schema de sesión, 1200 tokens salvo el perfil
off-800, el mismo contexto y ejecución secuencial. Hubo desconexiones intermitentes
del servidor; las muestras fallidas se excluyeron de los pares completos.

| Perfil | Actual: mediana latencia / prompt tokens | Candidata: mediana latencia / prompt tokens | Pares completos |
|---|---:|---:|---:|
| Thinking off, 1200 | 5,04 s / 4939 | 4,86 s / 3512 | 6 |
| Thinking off, 800 | 5,39 s / 4939 | 4,89 s / 3512 | 5 |
| Thinking on, 1200 | 18,29 s / 4975 | 7,70 s / 3510 | 7 |

Con thinking apagado no se observaron truncamientos ni reparaciones en las
muestras válidas de estos perfiles. Con thinking activado y límite 1200, el prompt
actual tuvo 4 truncamientos primarios/reparaciones entre 8 muestras válidas; la
candidata no tuvo truncamientos entre 9 muestras válidas. Los datos de reasoning
tokens no estuvieron disponibles en el servidor. Estos resultados son orientativos:
hay variabilidad del modelo, caché y desconexiones; no prueban causalidad ni bastan
para cambiar producción.

## Límites y próximo criterio

- El perfil de 800/1200 mantuvo JSON válido en las muestras válidas de esta traza,
  pero no debe generalizarse a otros turnos o schemas sin nuevas pruebas.
- No activar la identidad candidata ni cambiar thinking global basándose solo en
  esta corrida. Revisar más ejemplos semánticos antes de promoverla.
- La suite automatizada completa y Ruff se ejecutaron después de los cambios; los
  resultados se registran en la sesión de desarrollo.
