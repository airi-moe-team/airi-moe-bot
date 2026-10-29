# Implementation Plan

- [x] 1. Establecer los checks de calidad puros en el dominio
- [x] 1.1 Limpiar artefactos de plantilla y detectar respuestas fuera de personaje
  - Eliminar marcas de plantilla del texto (`<|im_end|>`, `<|im_start|>`, `</s>`, `### Human:`, `### Assistant:`, y `User:`/`Assistant:` solo al inicio de línea) dentro de la limpieza existente.
  - Añadir detección de frases de asistente ("como modelo de lenguaje", "como una ia", "como asistente virtual") devolviendo el motivo detectado.
  - Garantizar que "User:" o "Assistant:" a mitad de una frase legítima no se eliminen.
  - _Requirements: 3.1, 3.3_

- [x] 1.2 Definir el contrato de issues y las utilidades de comparación
  - Modelar un issue de calidad con tipo cerrado, impacto cerrado, evidencia literal y origen (determinista o revisor).
  - Modelar el resultado del revisor con su validez explícita; cualquier anomalía debe producir "no válido" sin lanzar.
  - Implementar el cálculo de solapamiento de tokens normalizados entre borrador y revisión, con exclusión de fragmentos marcados.
  - Desactivar el umbral para borradores de menos de 25 tokens, exigiendo solo que no queden vacíos.
  - _Requirements: 2.4, 4.2, 4.6_

- [x] 1.3 Recortar despedidas de forma segura y ampliar la detección de repetición
  - Recortar la afirmación de marcha por límite de oración, no por subcadena.
  - Validar el residuo (longitud mínima, inicial mayúscula, puntuación terminal) y devolver si el recorte es aceptable.
  - Extender la detección de repetición a mensajes de usuarios con umbral de 60 caracteres normalizados.
  - _Requirements: 3.2, 3.5, 6.1, 6.2_

- [x] 2. Unificar las reparaciones en dos políticas
- [x] 2.1 Crear el punto único de reparación con presupuesto y registro
  - Sustituir las cinco ramas independientes por una operación única que reciba la política y su causa.
  - Registrar cada invocación con su propósito y su motivo, sin apilar dos veces la misma política.
  - Devolver "sin mejora" cuando la reparación no produzca texto utilizable, conservando la salida previa.
  - Respetar el contrato de sesión: conservar la decisión de permanecer activa y tratar el silencio como válido.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 8.1, 8.3_

- [x] 2.2 Implementar la política de parseo con causa específica
  - Cubrir los tres síntomas: generación cortada por longitud, respuesta vacía y JSON irrecuperable.
  - Construir la pista de reparación a partir del síntoma, sin cinco prompts distintos.
  - Reutilizar el turno original con la personalidad de Airi intacta.
  - No disparar la política en modo sesión cuando el silencio es deliberado.
  - _Requirements: 1.1, 1.3, 1.4, 1.6, 8.3_

- [x] 2.3 Implementar la política de calidad en modo revisión del borrador
  - Enviar el borrador como turno previo del modelo y la corrección como instrucción posterior.
  - Incluir todos los issues detectados en una sola instrucción, con su evidencia literal.
  - Exigir que la corrección no mencione el arreglo, no pida perdón y devuelva solo el JSON.
  - Aceptar la revisión solo si supera el umbral de solapamiento; en caso contrario, descartarla y aplicar el parche determinista.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 8.1_

- [x] 3. Añadir el verificador semántico de coherencia
- [x] 3.1 Construir la revisión con prompt corto y comportamiento fail-open
  - Usar los últimos 8-10 turnos etiquetados por autor, incluido el mensaje actual, más el borrador.
  - Ejecutar la revisión con rol de juez, sin la personalidad de Airi y con esfuerzo de razonamiento bajo.
  - Exigir evidencia literal para cada issue y descartar los que no la tengan.
  - Traducir cualquier excepción, timeout o JSON inválido a "no válido" para publicar el borrador limpio.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 8.2_

- [x] 3.2 Definir el gate de activación
  - Exponer una configuración de entorno para activar o desactivar la revisión, activada por defecto.
  - Omitir la revisión en turnos rápidos, citas y acciones no conversacionales.
  - Omitir la revisión cuando no hay texto que publicar (silencio válido).
  - Revisar también turnos 1-a-1, de regalo, de espectador, activos y proactivos con texto.
  - _Requirements: 5.1, 5.2, 5.3_

- [x] 3.3 Integrar la revisión en el pipeline y fusionar los issues
  - Ejecutar la revisión después de la limpieza determinista y antes de cualquier reparación de calidad.
  - Re-evaluar la calidad sobre el resultado de la política de parseo.
  - Combinar issues deterministas y del revisor, eliminando duplicados por tipo.
  - Aplicar el parche determinista final y marcar el turno como agotado cuando no haya más margen.
  - _Requirements: 1.3, 3.4, 4.1, 8.1, 8.3_

- [x] 4. Extender la telemetría y el diagnóstico
- [x] 4.1 Registrar propósitos y motivos de reparación por llamada
  - Publicar los propósitos nuevos de reparación y de revisión en el registro de llamadas.
  - Añadir el motivo de reparación a cada llamada de reparación.
  - Mantener la compatibilidad con las trazas antiguas que usan los cinco nombres previos.
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 4.2 Exponer el resultado de la revisión en la traza del turno
  - Añadir si la respuesta quedó en el hilo, la lista de issues y la duración de la revisión.
  - Añadir la marca de presupuesto de reparación agotado.
  - Asegurar que la traza sigue reflejando la última generación real.
  - _Requirements: 7.4, 7.6_

- [x] 4.3 Añadir el diagnóstico de reparaciones a la herramienta de trazas
  - Agrupar turnos por motivo de reparación y por presupuesto agotado.
  - Listar los identificadores de correlación para poder abrir cada caso.
  - Tratar los propósitos antiguos como desconocidos sin romper la salida.
  - Actualizar la lista de propósitos en la documentación de observabilidad.
  - _Requirements: 7.5, 10.1, 10.2, 10.3, 10.4_

- [x] 5. Integración, compatibilidad y regresión
- [x] 5.1 Cubrir con pruebas unitarias los checks puros
  - Artefactos de plantilla, incluido el caso de "User:" a mitad de frase.
  - Detección de fuera de personaje con positivos y negativos.
  - Recorte de despedida por oración: residuo corto, sin puntuación y con negaciones.
  - Solapamiento de tokens: idéntico, reescritura total y exclusión de fragmentos marcados.
  - Parseo del veredicto: válido, inválido y issue sin evidencia.
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 4.2, 6.1_

- [x] 5.2 Cubrir con pruebas de integración el presupuesto y los fallos
  - Turno que dispara truncamiento y repetición: nunca más de cuatro llamadas.
  - Revisor que falla: se publica el borrador limpio.
  - Orden correcto: parseo antes que calidad, sin evaluar calidad sobre salida vacía.
  - Modo sesión: el silencio no dispara reparación de parseo.
  - Configuración apagada: cero llamadas de revisión.
  - _Requirements: 1.3, 1.5, 4.3, 5.2, 5.3, 8.1, 8.2, 8.3_

- [x] 5.3 Verificar el alcance y regenerar la regresión
  - Confirmar que no se añaden reintentos de red ni mensajes de respaldo en personaje.
  - Confirmar que la verificación contra fuentes sigue limitada a la búsqueda web.
  - Confirmar que no se añaden comprobaciones de tema por términos.
  - Regenerar los transcripts golden y revisar que los cambios de comportamiento son intencionados.
  - Reproducir trazas nuevas para verificar que no hay divergencias.
  - _Requirements: 9.1, 9.2, 9.3, 9.4_
