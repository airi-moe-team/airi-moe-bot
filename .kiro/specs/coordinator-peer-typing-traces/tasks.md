# Implementation Plan

- [x] 1. Hacer visible la generación de respuestas coordinadas
- [x] 1.1 Cubrir primero la actividad visible con pruebas que fallen
  - Verificar que el indicador esté activo durante la generación de una respuesta y durante su reparación.
  - Verificar que se cierre tras éxito, silencio, error y cancelación, sin publicar mensajes por un silencio.
  - Verificar que la decisión de participación no active el indicador y que publicar siga requiriendo autorización del turno.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.4_

- [x] 1.2 Mostrar actividad únicamente durante la generación
  - Encerrar la generación primaria y la reparación en el indicador de escritura del canal.
  - Conservar la ausencia de indicador en las decisiones y las comprobaciones actuales antes de publicar.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Hacer diagnosticables las llamadas del modelo coordinado
- [x] 2.1 Cubrir primero los contextos de las llamadas con pruebas que fallen
  - Comprobar que las llamadas primaria y de reparación conservan el identificador del trabajo y se distinguen por propósito e índice.
  - Comprobar que la captura desactivada no guarda artefactos y que un fallo al capturar no altera la respuesta ni vuelca datos en los logs.
  - Mantener los casos de reparación agotada, silencio y máximo una reparación.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.3, 3.4_

- [x] 2.2 Asociar la respuesta de cada llamada al trabajo sin cambiar la conversación
  - Propagar metadatos de contexto a la llamada primaria y a su única reparación.
  - Informar de fallos de captura con identificador de trabajo y clase de error, sin registrar mensajes ni cuerpos del modelo.
  - Mantener los errores de modelo independientes de los fallos de escritura de artefactos.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.3_

- [x] 3. Aislar la captura privada en el despliegue
- [x] 3.1 Probar permisos y configuración con captura habilitada y deshabilitada
  - Verificar permisos restrictivos del directorio privado y de los archivos creados.
  - Comprobar que el despliegue selecciona el volumen persistente de cada bot por defecto y admite desactivar expresamente la captura.
  - Verificar que los volúmenes no se mezclan y que una ruta inválida no impide responder al modelo.
  - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

- [x] 3.2 Consolidar la configuración en el despliegue
  - Establecer en el Compose una ruta predeterminada escribible y persistente para ambos bots, con opción explícita de desactivación.
  - Retirar únicamente las definiciones antiguas de artefactos en los env de cada bot para evitar duplicar la fuente de configuración.
  - Restringir los permisos al crear los nuevos directorios privados sin modificar archivos ajenos preexistentes.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 4. Integrar y comprobar el comportamiento completo
- [x] 4.1 Confirmar que actividad, captura y publicación conviven sin regresiones
  - Ejecutar pruebas del worker y del almacenamiento de artefactos, luego suite completa y lint.
  - Verificar que el indicador se cierra en todos los caminos, que el job conserva su control de publicación y que los logs no revelan contenido.
  - Confirmar que no cambió el número máximo de reparaciones ni la semántica del silencio.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4_
