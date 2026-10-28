# Plan de implementación

- [x] 1. Construir el núcleo puro de percepción temporal (TDD)
- [x] 1.1 Resolver zona horaria y descomponer el instante en fecha, hora y franja
  - Resolver la zona desde `AIRI_TIMEZONE` (IANA) o, si falta, la zona local del proceso.
  - Fallback determinista y aviso único ante zona inválida; la etiqueta de zona distingue override de sistema.
  - Descomponer `now` en año, mes, día, hora, minuto, nombre de día y nombre de mes en español, sin depender del locale.
  - Asignar franja con fronteras fijas: 00–05 madrugada, 06–11 mañana, 12–19 tarde, 20–23 noche.
  - Tests de frontera exacta, cambio de día, DST de marzo y octubre en `Europe/Madrid` y zona del sistema vía `TZ`.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 6.1, 6.5_

- [x] 1.2 Formatear intervalos naturales y diferencias de calendario
  - Formato largo para la sección ("ahora mismo", minutos, horas, "ayer", días) y corto para etiquetas ("ahora", "hace N min", "hace N h", "ayer", "hace N días").
  - Decidir "ayer" por fecha local, no por división de 86400, para que la cambio de hora no produzca textos falsos.
  - Acotar intervalos negativos o inválidos a "ahora" sin romper el turno.
  - Tests de 0 s, 59 s, 60 s, 59 min, 60 min, 23 h, 26 h, 47 h, 49 h, 3 días y `ts` futuro.
  - _Requirements: 2.4, 2.5, 2.6, 2.7, 3.6_

- [x] 1.3 Agregar el contexto temporal del turno
  - Calcular el silencio de la persona desde su último registro antes de contarla en este turno.
  - Marcar primera interacción cuando no haya registro, sin inventar intervalo.
  - Calcular el silencio del canal con la marca más reciente entre historial persistido y captura pasiva del modo espectador.
  - Omitir el silencio del canal dentro de una cita; conservar el de la persona.
  - Devolver `None` cuando la feature está desactivada, sin efectos laterales.
  - Tests: usuario nuevo, historial sin marcas, búfer más reciente que el historial, cita en curso, feature apagada, determinismo byte a byte para el mismo `now`.
  - _Requirements: 2.1, 2.2, 2.3, 2.8, 5.2, 6.1, 6.5_

- [x] 2. Exponer configuración y diagnóstico de arranque
- [x] 2.1 Añadir las claves de entorno y su validación
  - Incorporar `AIRI_TIME_CONTEXT` (booleano, por defecto activo) y `AIRI_TIMEZONE` (texto, por defecto vacío) a los ajustes de aplicación.
  - Valor booleano no reconocido: default documentado más aviso único.
  - Documentar ambas claves y la nota de `TZ` para contenedores en `.env.example`.
  - Tests de defaults, lectura, valor inválido y precedencia.
  - _Requirements: 5.1, 5.4, 5.5_

- [x] 2.2 Registrar la zona resuelta al arrancar
  - Registrar en INFO la zona efectiva y su origen (override o sistema) al construir el cliente.
  - Reutilizar la resolución del dominio, sin duplicar reglas.
  - Test de que el aviso/origen se emite con override y con zona del sistema.
  - _Requirements: 1.4, 1.5, 1.6, 5.6_

- [x] 3. Redactar la sección de percepción en el prompt
- [x] 3.1 Renderizar la sección completa, compacta y proactiva
  - Versión completa: fecha con día de semana, hora local, franja, silencio de la persona y del canal.
  - Versión compacta para turnos breves: una línea con fecha, hora, franja y silencio de la persona.
  - Modo proactivo: añadir la relación entre franja e iniciativa permitida, sin planes de otra franja.
  - Cita en curso: sin línea de silencio de canal.
  - Incluir la regla de contexto-no-anuncio y la excepción de pregunta directa por hora o fecha.
  - Tests de contenido, ausencia con contexto `None`, tamaño relativo compacta vs completa y ausencia de datos internos.
  - _Requirements: 1.7, 1.8, 1.9, 2.9, 4.2, 4.4, 6.5_

- [x] 4. Integrar la percepción en todos los modos del turno
- [x] 4.1 Inyectar contexto y sección en la generación
  - Calcular el contexto una vez por turno a partir del instante del turno y de los datos previos a las mutaciones.
  - Insertar la sección al principio de las secciones dinámicas, antes de afinidad, en turnos normales y breves.
  - Mantener el orden relativo del resto de secciones y el contrato JSON sin cambios.
  - Degradar a turno sin sección si el cálculo falla, registrando el error en la traza sin abortar.
  - Tests: presencia y posición en normal, breve, espectador, activa y proactiva; paridad de comportamiento con la feature apagada.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.3, 7.1, 7.2, 7.3, 7.4_

- [x] 4.2 Persistir la marca temporal de cada intervención
  - Guardar el instante del turno en los mensajes de usuario y de asistente del historial público y del historial privado de cita.
  - Propagar la marca de las entradas pasivas al contexto efímero del modo espectador.
  - Mantener compatibilidad con historiales antiguos sin marca y sin subir la versión de esquema.
  - Tests: mensajes nuevos con marca, mensajes antiguos intactos, estado guardado y recargado sin pérdida, cita aislada.
  - _Requirements: 3.5, 3.7, 6.1, 7.2_

- [x] 5. Añadir cadencia temporal a la vista de inferencia
- [x] 5.1 Etiquetar las intervenciones humanas con tiempo relativo
  - Anteponer `[intervalo]` a los mensajes de usuario y de espectador con marca conocida, antes de la etiqueta de identidad.
  - No anteponer nada a los turnos de Airi para preservar el contrato JSON.
  - Conservar mensajes sin marca sin etiqueta y en su orden.
  - Mantener el comportamiento actual cuando no se pasa instante de referencia.
  - Idempotencia ante vistas ya etiquetadas y resistencia a textos de usuario que imiten el formato.
  - Recalcular etiquetas contra el instante de cada turno, sin persistirlas.
  - Tests: usuario, espectador, asistente sin prefijo, sin `now`, sin marca, idempotencia, imitación, dos instantes distintos.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.8, 7.1_

- [x] 5.2 Conectar las etiquetas en la construcción del turno
  - Pasar instante y zona resueltos a la vista de inferencia en turnos normales, breves, de sesión y de cita.
  - Verificar que los turnos breves solo recortan historial, no formato de etiqueta.
  - Tests de vista final en turno normal y breve con historial mixto con y sin marca.
  - _Requirements: 4.2, 4.3, 5.2, 7.1_

- [x] 6. Trazar y reproducir la percepción temporal
- [x] 6.1 Registrar en la traza lo que Airi percibió
  - Añadir a la traza del turno: activación, zona, fecha y hora local, día de semana, franja, minutos desde la última intervención de la persona y del canal.
  - No añadir contenido de mensajes ni datos adicionales.
  - Con la feature apagada, registrar solo el estado de activación.
  - Tests de campos presentes, ausentes y sin contenido textual.
  - _Requirements: 6.3, 6.4_

- [x] 6.2 Reproducir trazas nuevas y antiguas sin divergencia
  - Reconstruir la configuración temporal desde la traza cuando exista y caer a los ajustes actuales cuando no.
  - Conservar las marcas temporales de los mensajes dentro de la traza reproducida.
  - Verificar que las trazas existentes del repositorio siguen coincidiendo.
  - Tests de replay con traza antigua sin campos temporales y con traza nueva que los incluye.
  - _Requirements: 6.1, 6.2, 3.7_

- [x] 7. Añadir evaluación reproducible de naturalidad temporal
- [x] 7.1 Extender el arnés de evaluación con instantes y silencios fijos
  - Permitir que cada escenario fije su instante y el último contacto de la persona.
  - Añadir escenarios de madrugada, mañana, tarde, noche, mensaje dos minutos después, reaparición tras tres días y proactivo nocturno.
  - Comparar con la feature activa y apagada usando los mismos instantes.
  - _Requirements: 8.1, 8.2_

- [x] 7.2 Detectar recitado del reloj de forma determinista
  - Regla automática que marque hora literal y frases de reloj en la respuesta.
  - Reportar como no evaluable cualquier escenario sin datos suficientes, sin asumir éxito.
  - Tests de la regla con respuestas positivas y negativas.
  - _Requirements: 1.8, 8.3, 8.4_

- [x] 8. Cerrar con regresión completa y documentación operativa
- [x] 8.1 Ejecutar la suite y verificar no regresiones
  - Suite unitaria, de integración y de regresión sin fallos.
  - Replay de las trazas versionadas sin divergencias.
  - Comparación de prompt con la feature apagada idéntica al comportamiento anterior.
  - _Requirements: 7.1, 7.2, 7.3, 6.2_

- [x] 8.2 Actualizar documentación operativa
  - Documentar en `README`/`.env.example` cómo activar, desactivar, medir y revertir.
  - Explicar el caso de contenedor en UTC y cómo fijar la zona.
  - _Requirements: 5.5, 5.6_
