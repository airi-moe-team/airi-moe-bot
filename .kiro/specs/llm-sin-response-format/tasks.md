# Plan de implementación

- [x] 1. Eliminar el formato estructurado del transporte LLM
- [x] 1.1 Verificar primero que el payload omite `response_format`
  - Añadir pruebas para llamadas con esquema en modo estricto y no estricto, exigiendo ausencia de la propiedad.
  - Añadir cobertura para la combinación de herramientas y esquema, que ya no debe fallar por incompatibilidad con `response_format`.
  - _Requirements: 1.1, 1.2_

- [x] 1.2 Retirar la opción `response_format` del cliente
  - Quitar la lectura, propagación y estado de `LLM_RESPONSE_FORMAT` en la configuración y fábrica del cliente.
  - Eliminar la serialización de `response_format` y el rechazo de herramientas junto con esquema.
  - Ajustar las pruebas de configuración para verificar que el cliente ya no expone esa opción.
  - _Requirements: 1.1, 1.2, 2.2_

- [x] 2. Retirar la variable y validar regresión de salidas
- [x] 2.1 Limpiar la configuración de entorno
  - Eliminar `LLM_RESPONSE_FORMAT` de `.env` y `.env.example`.
  - Comprobar que no queda documentación operativa que sugiera configurar la variable.
  - _Requirements: 2.1_

- [x] 2.2 Ejecutar pruebas de regresión del parseo y del flujo de conversación
  - Verificar que siguen funcionando extracción JSON, normalización de GIF y fallbacks existentes.
  - Ejecutar las pruebas unitarias e integración relevantes para el cliente LLM y las salidas de conversación.
  - _Requirements: 3.1, 3.2_
