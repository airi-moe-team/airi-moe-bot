# Plan de implementación

- [x] 1. Preparar la variante compacta sin alterar el prompt de producción
- [x] 1.1 Consolidar reglas redundantes y aclarar prioridades en la candidata
  - Crear la candidata reduciendo repeticiones, conservando identidad, intención, honestidad, memoria/continuidad, límites relacionales y contrato.
  - Mantener el prompt actual como baseline inmutable para la comparación.
  - Verificar que la candidata es más corta y que las reglas esenciales siguen presentes.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 1.2 Proteger el comportamiento predeterminado y aislar la selección de variante
  - Añadir selección explícita de variante con el prompt actual como default.
  - Mantener la selección independiente de `quick`, del historial visible, del schema, del contrato de salida y del límite de tokens.
  - Probar que una llamada normal sin selector produce el prompt actual y que cambiar la variante solo cambia el system prompt.
  - _Requirements: 1.1, 1.2, 1.3, 2.4_

- [x] 2. Construir ejecución benchmark aislada con thinking activado
- [x] 2.1 Validar entrada y reconstruir cada muestra desde el mismo contexto
  - Cargar la traza de referencia y rechazarla antes de inferir si falta información necesaria.
  - Reconstruir estado e historial de forma independiente para cada muestra.
  - Confirmar configuración efectiva de thinking `on` y abortar antes de inferir si está apagada o no se puede verificar.
  - Evitar publicación en Discord y persistencia de mutaciones del turno.
  - _Requirements: 1.1, 1.2, 1.4, 5.2_

- [x] 2.2 Ejecutar pares de variantes en secuencia y conservar métricas por muestra
  - Ejecutar al menos cinco pares, alternando el orden entre A-B y B-A, sin concurrencia.
  - Registrar identificador de traza, variante, pareja/orden, hash y longitud del prompt, tiempos, usage y finish reason disponibles.
  - Registrar TTFT y tasa de salida solo cuando exista información suficiente; indicar explícitamente los valores no disponibles.
  - Representar fallos y datos faltantes sin inferir valores ni guardar contenido conversacional.
  - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.2, 5.3_

- [x] 3. Producir comparación agregada y comprobar calidad
- [x] 3.1 Calcular estadísticas pareadas del experimento
  - Calcular medianas y rangos por variante para tokens y latencias.
  - Reportar cantidad de muestras válidas/fallidas y pares completos, preservando asociación entre las dos muestras de cada pareja.
  - Separar interpretación de métricas de entrada/prefill de métricas de salida/generación.
  - Advertir cuando haya menos de cinco pares completos o solo datos exploratorios, sin formular conclusiones causales.
  - _Requirements: 3.3, 3.4, 3.5_

- [x] 3.2 Evaluar estructura y calidad sin retener respuestas privadas
  - Verificar parseo/schema, truncamiento y reglas esenciales en cada salida.
  - Incorporar calificaciones de relevancia, coherencia, proporcionalidad y personalidad sin incluir respuesta, historial o prompt en el reporte.
  - Marcar candidato no aceptable ante incumplimiento esencial aunque mejore una métrica de latencia.
  - _Requirements: 4.1, 4.2, 4.3, 5.1_

- [x] 4. Integrar y verificar el flujo completo de evaluación
- [x] 4.1 Cubrir con pruebas el recorrido controlado y los casos de fallo
  - Probar con LLM fake que el contexto y los argumentos se mantienen iguales entre variantes, salvo el texto de system prompt.
  - Probar el default de producción, el control de thinking, el orden alternado, el uso de estado limpio y el reporte sin texto sensible.
  - Probar usage ausente, TTFT no disponible, timeout, salida truncada y par incompleto.
  - Verificar que las métricas/resultados siguen asociados a variante, traza, pareja y orden.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 4.1, 5.1, 5.2, 5.3_

- [x] 4.2 Hacer accesible el benchmark sin afectar la ejecución habitual de Airi
  - Integrar la ejecución de referencia en un comando/runner de evaluación separado del camino de producción.
  - Exigir identificación explícita de traza y generar salida agregada local, sin texto del turno.
  - Verificar con una prueba de integración que la ejecución normal del bot conserva la variante actual.
  - _Requirements: 1.4, 3.1, 5.1, 5.2_

- [ ] 5. Evaluar una candidata focalizada para decisiones conversacionales sencillas
- [x] 5.1 Construir `decision_light_candidate` sin modificar `current`
  - Simplificar la orientación del GIF por acción/emoción observable sin cambiar el enum ni acoplarlo a `mood.label`.
  - Aclarar que los gestos narrativos de `reply` son opcionales y usar una instrucción positiva de respuesta directa.
  - Añadir pruebas de contrato para igualdad byte por byte de `current` y diferencias acotadas de la candidata.
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 5.2 Comparar la candidata y `current` con replay controlado
  - Añadir prueba de integración para la selección opt-in de la candidata.
  - Ejecutar repeticiones sobre la misma traza, con el mismo modelo y parámetros, registrando métricas de `primary` y separando reparación/revisión.
  - Informar parseo, truncamiento y reparaciones junto con tokens y latencia, sin atribuir a `primary` el tiempo de llamadas posteriores.
  - _Requirements: 3.1, 3.3, 4.1, 6.3, 6.4_

- [ ] 6. Promover las guías aprobadas al prompt de producción
- [x] 6.1 Actualizar el prompt predeterminado y conservar rollback
  - Tras aprobación humana, aplicar a `current` la guía de GIF observable, la respuesta directa y los gestos opcionales.
  - Mantener los enums y el schema sin cambios y conservar temporalmente la variante anterior para comparación/rollback.
  - _Requirements: 7.1, 7.2, 7.4, 7.5_

- [x] 6.2 Verificar aliases, parseo y comportamiento de producción
  - Comprobar `smile→happy`, `neutral→nod`, `shy→shy` y fallback de valores desconocidos.
  - Probar que JSON inválido o truncado sigue usando la política actual de reparación, independiente de los GIF.
  - Ejecutar suite completa y replay controlado; documentar quality/latencia y mantener opción de rollback.
  - _Requirements: 7.3, 7.4, 7.5_

- [ ] 7. Centralizar las definiciones visuales de GIF
- [x] 7.1 Añadir cobertura TDD para la semántica centralizada
  - Probar que el prompt full y compacto contiene una única sección `REACCIONES VISUALES Y SELECCIÓN DE GIF` y ningún encabezado antiguo `Guía de GIFs`.
  - Comparar los identificadores definidos en el catálogo con todos los valores canónicos permitidos salvo el sentinel `none`; verificar significados de `shy` y `wave`.
  - Probar que `gif` conserva la lista de valores permitidos pero su descripción solo remite a la sección semántica; cubrir variantes experimentales y rollback.
  - Probar que el prompt dinámico de ánimo no prescribe GIF ni acopla `mood.label`, y que las instrucciones de afinidad/cercanía social siguen presentes.
  - _Requirements: 8.1–8.7_

- [x] 7.2 Refactorizar constructor y prompt dinámico
  - Consolidar catálogo e instrucciones semánticas en una constante/sección única usada por full y compact.
  - Sustituir la frase de ánimo que acopla GIF y estado emocional, preservando afinidad/cercanía.
  - Eliminar definiciones duplicadas y revisar todas las variantes para que el rollback no reintroduzca contradicciones.
  - No alterar schema, enums, alias parser, personalidad, relaciones, memoria, parámetros ni flujo de retries.
  - _Requirements: 8.1–8.7, 8.10_

- [ ] 7.3 Ejecutar validación del prompt real y pruebas semánticas repetidas
  - Ejecutar suite completa, Ruff y `git diff --check`.
  - Capturar y verificar el system prompt incluido en una petición real al LLM.
  - Ejecutar repetidamente los seis escenarios de saludo tímido, pudor afectivo, acuerdo, logro, duda y despedida, con el mismo modelo/settings y sin publicar a Discord.
  - Registrar JSON válido, `finish_reason`, presencia de `content`, tokens/latencia, coherencia reply/GIF, calidad, reconsideración observable y bucles; no exponer razonamiento privado en el reporte.
  - Comparar con baseline únicamente si el prompt anterior puede ejecutarse bajo condiciones equivalentes; de lo contrario, etiquetar resultados como descriptivos.
  - _Requirements: 8.8–8.10_
