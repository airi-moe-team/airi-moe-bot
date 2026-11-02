# Plan de implementación

- [x] 1. Definir y verificar el resultado de la evaluación de invitación
- [x] 1.1 Cubrir decisiones válidas e inválidas con pruebas unitarias
  - Verificar que `accept` y `reject` son las únicas decisiones aceptadas.
  - Verificar que una respuesta incompleta o mal formada se considera error técnico, no aceptación ni rechazo.
  - Verificar normalización y límites del texto breve de respuesta.
  - _Requirements: 2.1, 2.5, 2.6_

- [x] 1.2 Implementar evaluación contextual segura
  - Proporcionar al evaluador el contexto de relación y afinidad disponible.
  - Instruir a Airi a valorar el contexto sin aplicar un umbral fijo ni una decisión predeterminada por rango.
  - Validar estructuralmente la respuesta del modelo.
  - Propagar timeout, error de proveedor y respuesta inválida como fallo de evaluación.
  - _Requirements: 2.1, 2.2, 2.3, 2.6_

- [x] 2. Integrar aceptación y rechazo en el comando de invitación
- [x] 2.1 Cubrir el flujo del comando con pruebas de integración
  - Probar aceptación con afinidad baja y alta.
  - Probar rechazo con afinidad baja y alta.
  - Comprobar que el evaluador se consulta antes de proponer escenas.
  - Comprobar que errores de evaluación no muestran escenas.
  - _Requirements: 1.1, 2.1, 2.3, 2.4, 2.5, 4.1_

- [x] 2.2 Ejecutar la decisión antes de mostrar las escenas
  - Aplicar las restricciones existentes de disponibilidad, pareja, cita activa y cooldown antes de llamar al evaluador.
  - Eliminar el bloqueo por afinidad mínima del comando.
  - En aceptación válida, comunicar la respuesta de Airi y continuar con la propuesta de escenas.
  - En rechazo, comunicar la respuesta contextual y terminar el flujo sin selector.
  - En fallo técnico, responder neutralmente sin convertir el fallo en rechazo emocional.
  - _Requirements: 1.1, 1.2, 2.1, 2.4, 2.5, 2.6_

- [x] 3. Preservar el inicio transaccional y restricciones de cita
- [x] 3.1 Verificar los efectos de rechazo y fallo
  - Comprobar con pruebas que rechazo y fallo no crean ni persisten una sesión.
  - Comprobar que no cambian afinidad, `last_date` ni cooldown.
  - _Requirements: 3.1, 4.2_

- [x] 3.2 Quitar el segundo umbral y mantener las revalidaciones
  - Eliminar el filtro de afinidad mínima al confirmar la escena.
  - Conservar las revalidaciones de cita activa, pareja y cooldown al elegir escena.
  - Crear sesión, actualizar `last_date` y persistir solo tras la selección confirmada.
  - Verificar con pruebas que una aceptación sin selección todavía no inicia la cita ni consume cooldown.
  - _Requirements: 1.1, 1.2, 3.2, 3.4, 4.3, 4.4_

- [x] 4. Validar regresiones y consecuencias de las citas
- [x] 4.1 Verificar compatibilidad con las reglas existentes
  - Comprobar que cooldown, exclusividad de cita activa y restricciones de relación siguen bloqueando la invitación cuando corresponde.
  - Verificar que la afinidad puede seguir subiendo o bajando durante la cita y que el cierre conserva los desenlaces actuales.
  - Ejecutar las pruebas unitarias y de integración relevantes del flujo de citas.
  - _Requirements: 1.2, 3.3, 3.4, 4.4_
