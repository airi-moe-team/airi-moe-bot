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
