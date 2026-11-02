# Plan de implementación

- [ ] 1. Hacer explícita la cobertura y el resultado de cada replay
- [x] 1.1 Definir checks comparables y estados no verificables
  - Escribir primero pruebas para checks aplicables y checks que el modo no ejecuta.
  - Representar separado el resultado de un check y la cobertura global completa/parcial.
  - Mantener `matches_original` como resumen de checks comparables sin confundirlo con cobertura completa.
  - Verificar que la ausencia de datos externos no se cuente como divergencia.
  - _Requirements: 1.2, 1.3, 1.4, 6.1, 6.4_

- [x] 1.2 Añadir diagnóstico por etapa de búsqueda y tarea
  - Probar estados diferenciados para decisión, resultado, grounding y contexto de tarea.
  - Marcar como no evaluada la decisión cuando el modo reutilice la respuesta guardada.
  - Informar discrepancia de consulta por separado de búsqueda vacía y captura ausente.
  - _Requirements: 1.2, 1.3, 6.1, 6.2, 6.3_

- [ ] 2. Proteger las trazas normales y habilitar captura local opt-in
- [x] 2.1 Redactar contenido web al serializar trazas normales
  - Escribir primero pruebas que demuestren que consultas y contexto web no aparecen en una serialización por defecto.
  - Conservar en memoria los datos necesarios para completar el turno y conservar metadatos no sensibles de estado.
  - Mantener la lectura de trazas históricas que sí contienen los campos de texto web.
  - Actualizar las expectativas de observabilidad para el nuevo límite de privacidad.
  - _Requirements: 3.1, 3.5, 7.1_

- [x] 2.2 Escribir sidecars de búsqueda solo con captura activada
  - Probar que, sin opt-in, solo se escribe la traza redactada y no se crea un artefacto de búsqueda.
  - Capturar consulta y resultados estructurados con estado explícito de no solicitada, vacía, con resultados o con error.
  - Vincular el artefacto a la traza y rechazar reemplazos accidentales de archivos existentes.
  - Escribir de forma atómica y con permisos locales restrictivos; no incluir secretos.
  - _Requirements: 3.2, 3.3, 3.4_

- [ ] 3. Validar y consumir capturas de búsqueda sin red
- [x] 3.1 Leer y validar artefactos locales versionados
  - Probar schema, tamaño máximo, `correlation_id`, estados válidos y resultados estructurados.
  - Rechazar artefactos inválidos o incompatibles con un error que no vuelque su contenido.
  - Aceptar como éxito reproducible el estado capturado de cero resultados.
  - _Requirements: 2.4, 2.5, 7.3_

- [x] 3.2 Responder al puerto de búsqueda con evidencia capturada coincidente
  - Probar consulta coincidente después de normalización conservadora, consulta distinta y captura ausente.
  - Devolver notas vacías para una captura vacía válida y no reutilizar evidencia ante mismatch.
  - Asegurar mediante fake/spy que el adaptador no inicia HTTP ni accede a credenciales.
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 6.3_

- [ ] 4. Aportar contexto privado mediante fixture lateral
- [x] 4.1 Validar e inyectar fixtures de contexto de tarea
  - Escribir primero pruebas de fixture válido, campos inválidos, exceso de tamaño y archivo ilegible.
  - Reutilizar límites y normalización del contexto de tarea existente.
  - Rechazar el fixture completo antes de llamar al LLM cuando no sea válido.
  - Inyectar el marco validado al turno solo en los modos que admiten inferencia.
  - _Requirements: 5.1, 5.4_

- [x] 4.2 Evitar filtraciones del fixture de tarea
  - Probar que objetivo, restricciones y progreso no aparecen en trazas, sidecars web ni mensajes de error.
  - Registrar únicamente presencia del fixture y versión de esquema como metadatos no sensibles.
  - Marcar continuidad como no evaluada cuando el fixture no se proporcione.
  - _Requirements: 5.2, 5.3, 7.3_

- [ ] 5. Integrar los modos de replay con permisos explícitos
- [x] 5.1 Mantener el modo predeterminado aislado y compatible
  - Probar que la invocación sin flags usa la respuesta guardada y no crea clientes de LLM ni de búsqueda.
  - Mantener la reconstrucción de estado y el replay de trazas existentes.
  - Reportar como no verificables las etapas para las que una traza histórica no tenga datos.
  - _Requirements: 1.1, 1.3, 7.1_

- [x] 5.2 Ejecutar replay conductual con LLM y búsqueda capturada
  - Probar que el modo requiere una captura indicada y válida antes de invocar el LLM.
  - Reejecutar decisión de búsqueda y síntesis con el backend configurado, usando solo el adaptador capturado para búsqueda.
  - Informar el backend LLM configurado antes de iniciar inferencia.
  - Comparar decisión y consulta nuevas con la captura sin ocultar cambios de comportamiento.
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 6.2, 6.3_

- [x] 5.3 Separar permisos de inferencia y búsqueda live
  - Probar que `--live` reejecuta el LLM y mantiene web deshabilitada por defecto.
  - Habilitar un cliente de búsqueda real únicamente con el permiso web live adicional.
  - Rechazar combinaciones inválidas antes de inicializar cualquier cliente externo.
  - Asegurar que ni el modo live ni el conductual publican a Discord o persisten estado productivo.
  - Diferenciar errores de servicio de divergencias de replay y conservar resultados de muestras anteriores.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 6. Cerrar integración, regresiones y ayuda de uso
- [x] 6.1 Cubrir flujos end-to-end y regresión histórica
  - Construir un caso sintético y redactado equivalente a `1380da81d040` con búsqueda capturada vacía.
  - Verificar diferencias entre búsqueda no solicitada, resultado vacío, captura ausente y consulta distinta.
  - Cubrir resultados con evidencia, fallo de LLM, fixture presente/ausente y ausencia de red donde corresponda.
  - Reproducir fixtures históricos y asegurar que checks nuevos se reportan como no verificables, no como fallos.
  - _Requirements: 6.1, 6.3, 7.1, 7.2, 7.3_

- [x] 6.2 Completar contrato de CLI y ejemplos seguros
  - Añadir ayuda de CLI para modo determinista, conductual, live y permiso web independiente.
  - Explicar captura local, fixture de tarea, resultado parcial y estados no verificables con ejemplos de invocación.
  - Probar que la ayuda no implica permisos por defecto y que opciones incompatibles se describen claramente.
  - _Requirements: 4.3, 4.4, 6.4, 7.4_
