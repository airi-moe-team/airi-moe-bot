# Implementation Plan — airi-interaccion-natural

## Fase 1 — Escucha pasiva (completada)

- [x] 1. Establecer la base del modo espectador: configuración y detección local
  - [x] 1.1 Añadir las variables de configuración del modo espectador
    - Definir interruptor global para activar/desactivar la escucha pasiva
    - Definir límite de tamaño del buffer por canal y su TTL
    - Definir umbral de afinidad, probabilidades por señal y cooldown
    - Ejecutar TDD: test rojo de lectura de configuración → valores por defecto
    - _Requirements: 1.3, 2.3, 4.5, 4.7, 5.8_
  - [x] 1.2 Implementar el matcher de temas sobre el perfil de gustos
    - Extraer gustos positivos del perfil canónico y preferencias vigentes
    - Normalizar texto y generar patrón con límites de palabra sin duplicar lista
    - Refrescar el patrón si cambia el perfil; alias solo si están declarados
    - Test rojo→verde: sin perfil no hay patrón; con perfil detecta coincidencias
    - _Requirements: 2.2, 2.6, 2.7, 2.8, 2.9_
  - [x] 1.3 Implementar la evaluación de señales de activación
    - Detectar mención directa, respuesta a Airi y nombre explícito
    - Evaluar coincidencia de tema y umbral de afinidad como señales independientes
    - Resolver la activación: mención garantizada; tema/afinidad mediante tirada
    - Reutilizar generador de azar y reloj inyectables para reproducibilidad
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 4.4_

- [x] 2. Construir la memoria del observador: buffer y snapshot efímero
  - [x] 2.1 Crear el buffer pasivo por canal en memoria
    - Registrar mensajes válidos sin invocar al LLM ni publicar nada
    - Aplicar límite FIFO y descarte por TTL con reloj inyectable
    - Excluir bots, comandos, otros canales y contenido vacío
    - Vaciar el buffer al reiniciar conversación o temporada
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 2.2 Generar el snapshot efímero de la intervención
    - Tomar el mensaje activador una sola vez y ventana reciente con autores
    - Recortar el snapshot a un máximo configurable y sin duplicados del turno
    - Evitar mezclar el buffer con el historial persistido por canal
    - _Requirements: 3.1, 3.2, 3.5_
  - [x] 2.3 Gestionar consumo y retención del snapshot
    - Al publicar con éxito, marcar consumidos solo los mensajes del snapshot
    - Si la generación/publicación falla, retener mensajes hasta su TTL
    - Garantizar que ningún mensaje aparezca dos veces en turnos consecutivos
    - _Requirements: 3.1, 3.3, 3.4, 4.6, 5.7_

- [x] 3. Integrar la intervención espontánea en el flujo de turnos
  - [x] 3.1 Conectar la activación al pipeline de mensajes
    - Evaluar señales tras el debounce y antes del dispatcher por canal
    - Emitir a lo sumo un turno por evento elegible; señales combinadas → un turno
    - Mantener la garantía de respuesta cuando la activación es por mención
    - _Requirements: 2.1, 2.4, 4.2, 4.3_
  - [x] 3.2 Adaptar la generación de respuesta al turno espontáneo
    - Inyectar el snapshot como contexto efímero etiquetado de forma interna
    - Conservar el prompt habitual (personalidad, gustos, afinidad) sin revelar
      reglas, umbrales ni el motivo del despertar
    - Permitir que la respuesta sea una reacción natural sin obligación de pregunta
    - _Requirements: 3.1, 3.2, 3.6_
  - [x] 3.3 Implementar la política de frecuencia y concurrencia
    - Aplicar cooldown por canal y autor tras publicar una intervención espontánea
    - Ejecutar la tirada local antes de cualquier llamada al LLM
    - Si la tirada falla: silencio, sin LLM y sin iniciar el cooldown
    - Respetar turnos en curso y debounce antes de despachar
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 4.7_

- [x] 4. Observabilidad, desactivación y compatibilidad
  - [x] 4.1 Registrar los eventos del modo espectador en las trazas
    - Añadir campos aditivos al evento de turno: motivo, snapshot y tirada
    - Mantener la reproducibilidad de `airi-replay` y el límite de tamaño de traza
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 4.2 Asegurar el comportamiento con el modo desactivado
    - Sin modo espectador: flujo actual intacto, salvo menciones/respuestas a Airi
    - Ejecutar la suite completa: sin regresiones y con los fakes existentes
    - Añadir pruebas de integración del pipeline con LLM falsos y relojes
    - _Requirements: 1.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

- [x] 5. Cierre del incremento: validación extremo a extremo
  - [x] 5.1 Probar el escenario del ejemplo de usuario
    - Simular canal activo sin menciones y mensaje sobre un gusto de Airi
    - Verificar activación por tema con tirada ok y respuesta contextual coherente
    - Verificar inactividad de Airi cuando la señal o la tirada no lo permiten
    - _Requirements: 1-5 según corresponda._
  - [x] 5.2 Correr la suite completa y documentar el estado de la feature
    - Suite de pytest en verde con y sin el modo espectador activado
    - Confirmar ausencia de llamadas LLM cuando no hay intervención
    - Preparar el flag de configuración para activar en producción
    - _Requirements: 5.8_

- [x] 6. Perfil estable de gustos
  - [x] 6.1 Perfil canónico configurable por entorno
    - Definir `AIRI_PROFILE` (JSON: loves/dislikes/favorite_food/favorite_flower)
    - Parseo tolerante: vacía o inválida ⇒ warning y fallback al perfil persistido/defaults
    - Al arrancar, si está definida y válida, persistirla en `world["preferences"]` con transacción
    - Matcher y prompt de gustos leen esa misma fuente del estado (sin listas duplicadas)
    - _Requirements: 2.6, 2.10, 2.11_
  - [x] 6.2 Congelar gustos ante el autodescubrimiento
    - Retirar las claves `tastes.*` de la allowlist de cambios de identidad
    - Actualizar el texto de reglas del prompt y los tests de self_model afectados
    - Verificar que un self_update de gustos ya no aplica y el historial queda íntegro
    - _Requirements: 2.12_

- [x] 7. Handoff y consumo del trigger
  - [x] 7.1 Continuación natural tras una intervención de Airi
    - El interlocutor puede responder UNA vez dentro de la ventana de handoff sin cooldown
    - El cooldown se re-arma después del handoff; la cadena no crece sola
    - La decisión y la traza registran razón "handoff"
    - _Requirements: 4.3, 4.6_
  - [x] 7.2 Consumir el mensaje disparador del buffer
    - Seguir los ids de los mensajes unidos por debounce y consumirlos con el snapshot
    - El tema no queda latente en el buffer tras publicar la respuesta
    - _Requirements: 3.3, 3.4_

- [x] 8. Sembrado inicial de actividad humana al arrancar
  - [x] 8.1 Implementar la heurística reutilizable de "último mensaje sin respuesta"
    - Añadir `_epoch` y `pending_user_message` en `client.py`
    - Validar humano, no comando, contenido/adjuntos y antigüedad opcional (`max_age=None` para sembrado)
    - Ejecutar TDD: casos rojo→verde para filtros y `max_age`
    - _Requirements: 6.1, 6.2, 5.1_
  - [x] 8.2 Sembrar `last_human_activity` al arrancar
    - Corrutina aislada `seed_last_human_activity(client)` con try/except y log
    - Leer `history(limit=1)`, aplicar heurística y llamar a `record_human_activity(channel_id, now=epoch)`
    - Solo ejecutar si `load_policy().enabled`; sin cambios en `SpectatorSessionRegistry`
    - _Requirements: 6.1, 6.2, 5.1_
  - [x] 8.3 Armar temporizador proactivo inicial con delay 0 no bloqueante
    - Implementar `arm_proactive_timer(channel, delay)` con `asyncio.sleep(max(0, delay))`
    - Cancelar temporizador proactivo previo y programar la tarea en `timers`
    - Ejecutar turno proactivo vía `dispatcher.submit` tras el delay
    - _Requirements: 4.1, 4.2, 6.3_
  - [x] 8.4 Integrar en el arranque y cubrir con pruebas
    - Envolver `resume_pending` + sembrado en `on_ready_extra` condicionado
    - Pruebas unitarias/integración: filtrado, sembrado y delay 0
    - _Requirements: 5.8, 6.1, 6.2_

## Fase 2 — Naturalidad conversacional y coherencia (implementada; aprobación humana pendiente)

> Orden obligatorio: construir el harness y capturar el baseline **antes** de
> modificar el prompt. No marcar una tarea como completada sin su test.
> Las casillas marcadas tienen implementación y cobertura automática. La tarea
> 15 sigue pendiente y las aprobaciones humanas de `spec.json` no se tocan.

- [x] 9. Construir el harness de evaluación de interacción (`R12`)
  - [x] 9.1 Definir escenarios y modelo de registro
    - Crear `src/airi/evaluation/interaction.py` sin modificar las métricas románticas de `narrative.py`
    - Definir `InteractionScenario` y los siete escenarios: pregunta directa, corrección, saludo breve, preferencia corregida, desacuerdo, charla casual y despedida
    - Reutilizar `airi.evaluation.runner.run_scenario` o un adaptador equivalente
    - Tests: los siete IDs existen, son únicos y cada uno tiene turnos
    - _Requirements: 12.1_
  - [x] 9.2 Implementar métricas objetivas y agregación de rúbrica
    - Medir `question_only_replies`, `repeated_closings`, `gesture_density`, `stacked_gestures`, `prefab_farewells`, `schema_failures` y `state_contradictions`
    - Agregar puntuaciones 0-2 de comprensión, naturalidad, continuidad, individualidad y coherencia; máximo 70
    - Tests rojo→verde para cada métrica y para el total de rúbrica
    - _Requirements: 12.2, 12.6_
  - [x] 9.3 Añadir el CLI de evaluación con modo live
    - Crear `tools/interaction_eval.py` con `--run`, `--live`, `--baseline`, `--out` y `--json`
    - `--live` genera los siete escenarios contra el LLM configurado en `LLM_BASE_URL` (por defecto `http://127.0.0.1:7000`), usando `build_llm` y `ConversationService` sin pasar por Discord ni persistir estado real
    - Permitir `--repeat` para repetir generaciones cuando el muestreo no sea determinista y `--base-url`/`--model` para fijar explícitamente el endpoint y el modelo de la comparación
    - Devolver código de salida distinto de cero ante regresión crítica
    - Tests del CLI con `FakeLLM` y JSONL temporales; el modo live no se ejecuta en la suite automática sin red
    - _Requirements: 12.3, 12.4, 12.5, 12.10_
  - [x] 9.4 Documentar el formato de registros y artefactos
    - Documentar campos obligatorios: escenario, turno, entrada, salida, modelo, prompt, parámetros, `finish_reason`, validación y puntuaciones
    - Ejemplo mínimo en el docstring del módulo y en `eval/README.md`
    - _Requirements: 12.5_

- [x] 10. Capturar la línea base antes de tocar el prompt (`R12`)
  - [x] 10.1 Congelar prompt, modelo y parámetros actuales
    - Registrar versión o hash del prompt, modelo exacto, temperatura, contexto y plantilla
    - Ejecutar los siete escenarios con `interaction_eval.py --live --out <baseline>.jsonl`
    - Guardar salidas originales, `finish_reason` y estado de parseo
    - Artefacto: `eval/baseline-20261026.jsonl`
    - _Requirements: 12.3, 12.4, 12.5_
  - [x] 10.2 Revisar y puntuar el baseline
    - Aplicar la rúbrica fija de 0-2 por criterio
    - Registrar fortalezas y fallos observados sin modificar todavía el prompt
    - Conservar los artefactos para la comparación posterior
    - Resultado: 46/70; detalle en `eval/README.md`
    - _Requirements: 12.2, 12.8_

- [x] 11. Prioridad de intención y respuesta directa (`R7`)
  - [x] 11.1 Añadir el bloque de intención al prompt
    - Crear `INTENT_PRIORITY_PROMPT` en `src/airi/domain/prompts.py`
    - Insertarlo después de `DIÁLOGO` y antes de `VARIEDAD Y NATURALIDAD`
    - Incluir: identificar intención, responder primero, preguntas opcionales, no convertir experiencia en entrevista y no cambiar de tema
    - Tests: el prompt contiene las reglas y el orden esperado
    - _Requirements: 7.1, 7.4, 7.5, 7.6_
  - [x] 11.2 Reforzar la corrección explícita
    - Conservar la nota `=== CORRECCIÓN DEL USUARIO (PRIORIDAD) ===` y la memoria de corrección existentes
    - Añadir tests de pregunta directa y de corrección por evasión
    - Verificar que la respuesta reconoce el error y vuelve a la pregunta original
    - _Requirements: 7.2, 7.3, 7.7_
  - [x] 11.3 Mantener la red anti-interrogatorio
    - Conservar `QUESTION_CLOSE_REPAIR_PROMPT` y `strip_trailing_question`
    - Añadir `strip_trailing_questions` para varios cierres interrogativos encadenados y corregir la asignación inmutable de `ModelOutput`
    - Añadir cobertura de integración para cierre con pregunta en charla casual
    - Verificar que las citas quedan fuera de la reparación
    - _Requirements: 7.8_

- [x] 12. Naturalidad narrativa y proporcionalidad (`R8`)
  - [x] 12.1 Integrar las reglas de naturalidad narrativa en el prompt
    - Integrar las reglas R8 en el bloque `VARIEDAD Y NATURALIDAD` de `SYSTEM_PROMPT`
    - Incluir: acciones opcionales, no apilar gestos, alternativas a la timidez, variar estructura y prioridad de la naturalidad
    - Eliminar cualquier regla de número fijo de palabras
    - Tests: no se introduce un límite fijo de palabras y las reglas nuevas están presentes
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [x] 12.2 Ajustar proporcionalidad y cierres
    - Añadir reglas de respuesta breve para saludo, mensaje corto y despedida
    - Evitar cierres prefabricados y preguntas para impedir que la persona termine
    - Añadir `limit_narrative_actions` como red determinista de una acotación por respuesta
    - Tests de longitud proporcional y de fórmulas de despedida
    - _Requirements: 8.7, 8.8, 8.9_
  - [x] 12.3 Medir la naturalidad del candidato
    - Ejecutar los escenarios de saludo, charla casual y despedida
    - Comparar densidad de acotaciones, gestos acumulados y cierres repetidos contra baseline
    - Resultado: `stacked_gestures=0`; densidad 0.308 vs 0.154; se documenta la regresión de calidad
    - _Requirements: 8.1-8.9, 12.6_

- [x] 13. Personalidad observable y opiniones propias (`R9`)
  - [x] 13.1 Añadir el bloque de personalidad y opiniones
    - Crear `PERSONALITY_TENDENCIES_PROMPT` con los seis rasgos como tendencias observables
    - Incluir opinión razonada, desacuerdo respetuoso y prohibición de inventar experiencias
    - Tests: el bloque existe y no duplica reglas de romance/afinidad
    - _Requirements: 9.1, 9.2, 9.3, 9.6, 9.7, 9.8_
  - [x] 13.2 Cubrir opinión y desacuerdo
    - Escenario de pregunta directa: elige y argumenta antes de preguntar
    - Escenario de desacuerdo: discrepa sin atacar ni ceder automáticamente
    - Verificar que los ejemplos son fixtures y no lógica hardcodeada
    - _Requirements: 9.4, 9.5, 12.12_

- [x] 14. Memoria consolidada y preferencias vigentes (`R10`)
  - [x] 14.1 Ampliar el modelo de memoria de forma compatible
    - Añadir metadatos aditivos: `updated_at`, `source`, `status`, `confidence`, `scope`, `topic`
    - Normalizar registros antiguos al leerlos sin romper `data/state.json`
    - Tests de compatibilidad con memorias existentes
    - _Requirements: 10.8_
  - [x] 14.2 Implementar consolidación y precedencia
    - Fusionar duplicados exactos y casi exactos; no acumular versiones redundantes
    - Marcar correcciones explícitas como vigentes y anteriores como `superseded` cuando el tema sea identificable
    - No mezclar usuarios ni promover inferencias a hechos
    - Tests de corrección, duplicados, contradicción e aislamiento entre usuarios
    - _Requirements: 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_
  - [x] 14.3 Ajustar el prompt de memoria
    - Añadir `MEMORY_USAGE_PROMPT`: priorizar información vigente y relevante, no recitar, respetar correcciones
    - Excluir `superseded` del prompt y añadir una nota determinista de memoria relevante cuando el tema coincide con el mensaje actual
    - Tests de prompt y de recuperación de memoria
    - _Requirements: 10.1, 10.2, 10.3_
  - [x] 14.4 Verificar preferencias canónicas de Airi
    - Comprobar que flor, comida y gustos salen de `world["preferences"]`/`AIRI_PROFILE`
    - Verificar que `self_update` no muta `tastes.*` y que no se acumulan versiones contradictorias
    - _Requirements: 10.9, 2.10, 2.11, 2.12_

- [x] 15. Coherencia de despedida, actividad y estado (`R11`)
  - [x] 15.1 Documentar y probar el contrato normal vs. sesión
    - Verificar que `stay_active` solo existe en `SESSION_RESPONSE_SCHEMA`
    - Verificar que en modo normal se fuerza `True` y que un campo extra no cambia el estado
    - Tests de campos ausentes, desconocidos, nulos y tipos inválidos
    - _Requirements: 11.3, 11.8_
  - [x] 15.2 Cubrir la matriz de `disconnect`/`stay_active`
    - Casos: `leave=false` + `stay_active=true`; `leave=false` + `stay_active=false`; `leave=true` con motivo; `leave=true` sin motivo
    - Integración: recepción de mensajes después de un apagado y recuperación del contexto
    - Añadir datos de traza suficientes: `kind`, timestamps, origen del cierre y correlación
    - _Requirements: 11.1, 11.2, 11.4, 11.5, 11.9_
  - [x] 15.3 Separar despedida personal y apagado global
    - Verificar que una despedida a una persona no cierra el bot
    - Verificar que el apagado global solo se solicita tras publicar/persistir y cuando el estado lo confirma
    - Tests de cierre manual vs. cierre decidido por el modelo
    - _Requirements: 11.5, 11.6, 11.7_

- [x] 16. Evaluación candidata y cierre (`R12`)
  - [x] 16.1 Ejecutar los siete escenarios con el candidato
    - Usar el mismo modelo, parámetros, contexto y prompt efectivo que el baseline
    - Repetir generaciones cuando el muestreo permita variación
    - Guardar artefactos completos y puntuaciones de rúbrica
    - Artefacto final: `eval/candidate-20261026-v9-scored.jsonl` (60/70)
    - _Requirements: 12.3, 12.4, 12.5_
  - [x] 16.2 Comparar baseline y candidato
    - Calcular deltas narrativos y técnicos por separado
    - Rechazar regresiones graves en coherencia, privacidad, estado o formato de salida
    - Confirmar mejora agregada sin ocultar casos críticos
    - Resultado: +14 de rúbrica, 0 regresiones críticas, 0 fallos de formato/estado; regresión de calidad documentada
    - _Requirements: 12.6, 12.7, 12.8, 12.11_
  - [x] 16.3 Cerrar la validación técnica
    - Ejecutar la suite completa, Ruff y las pruebas de fase 1
    - Documentar la limitación de `airi-replay` determinista y el uso de `--live` para regenerar
    - Actualizar el estado de la spec sin marcar aprobaciones humanas como automáticas
    - Resultado: `946 passed`, Ruff limpio; `eval/README.md` documenta la limitación
    - _Requirements: 12.9, 12.10, 12.12_

## Fase 3 — Identidad narrativa y eficiencia de generación (pendiente de aprobación)

> Ejecutar estas tareas solo después de revisar y aprobar los requisitos, el diseño y
> este plan actualizado. Evaluar identidad y rendimiento por separado.

- [x] 17. Incorporar identidad narrativa compacta de Airi (`R13`)
  - [x] 17.1 Diseñar una candidata de identidad sin alterar aún el prompt predeterminado
    - Definir premisa ficticia breve, perspectiva/opiniones, preferencias con motivos y
      contradicciones moderadas.
    - Distinguir identidad estable, experiencias confirmadas y roleplay.
    - Preservar honestidad, límites afectivos y la decisión previa contra tsundere.
    - _Requirements: 13.1-13.6_
  - [x] 17.2 Corregir la concatenación del prompt y cubrir composición
    - Separar correctamente la instrucción de “contar algo tuyo” de la siguiente regla.
    - Añadir tests para separación, contenido, orden y ausencia de contradicciones con
      memoria/romance.
    - _Requirements: 13.1-13.4_
  - [x] 17.3 Evaluar identidad con seis escenarios controlados
    - Incluir pregunta personal, aclaración, identidad, desacuerdo, charla casual y
      corrección explícita.
    - Mantener iguales modelo, parámetros, historial, thinking y contrato entre baseline
      y candidata.
    - Puntuar repetición, perspectiva, naturalidad, respuesta directa y schema; no
      adoptar automáticamente la candidata.
    - _Requirements: 12.3-12.8, 13.1-13.6_

- [x] 18. Diagnosticar latencia, thinking y recuperación JSON (`R14`)
  - [x] 18.1 Confirmar el modo y el schema de la traza investigada
    - Identificar si el turno era normal o de sesión antes de evaluar `stay_active`.
    - Añadir/regenerar cobertura del contrato JSON aplicable; no tratar la clave de sesión
      como extra inválida en `SESSION_RESPONSE_SCHEMA`.
    - _Requirements: 11.3, 11.8, 14.4_
  - [x] 18.2 Registrar y reportar coste y truncamiento
    - Capturar tiempos, tokens disponibles, `finish_reason`, truncamiento y reparación.
    - Conservar valores ausentes como no disponibles y separar métricas técnicas de la
      evaluación narrativa.
    - _Requirements: 12.5, 12.6, 14.1, 14.2_
  - [x] 18.3 Comparar perfiles técnicos sin tocar producción
    - Probar perfiles con y sin thinking y límites de salida calibrados al schema activo.
    - Verificar JSON válido en modo normal y sesión; medir latencia y tasa de reparación.
    - Recomendar cambios solo con resultados repetidos y sin regresiones esenciales.
    - _Requirements: 14.2-14.5_

> Resultados live y limitaciones: `eval/airi-pendientes-20261027.md`. La candidata
> permanece opt-in; no se modificó el perfil de producción.
