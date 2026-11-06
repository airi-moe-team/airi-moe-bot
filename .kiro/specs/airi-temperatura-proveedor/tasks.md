# Plan de implementación

- [x] 1. Garantizar con pruebas que Airi delega la temperatura al proveedor
- [x] 1.1 Cubrir la omisión del parámetro en el adaptador HTTP
  - Añadir pruebas para solicitudes estándar y streaming que inspeccionen el payload capturado.
  - Verificar que las variables antiguas no hacen que aparezca `temperature`.
  - _Requirements: 1.1, 2.1, 3.1_

- [x] 1.2 Cubrir llamadas de integración sin temperatura explícita
  - Actualizar pruebas de integración del glue y de búsqueda web para comprobar que el payload no contiene temperatura.
  - Adaptar los fakes para que las llamadas ya no acepten ni registren este parámetro.
  - _Requirements: 1.2, 3.1, 3.2_

- [x] 2. Eliminar el control de temperatura del contrato y las llamadas de Airi
- [x] 2.1 Simplificar el contrato y la configuración del cliente LLM
  - Quitar temperatura de las interfaces públicas de chat.
  - Eliminar lectura de defaults y variables de entorno relacionadas con temperatura.
  - Quitar la omisión configurable de temperatura del armado de configuración.
  - _Requirements: 2.1_

- [x] 2.2 Omitir temperatura en todas las operaciones LLM
  - Dejar de incluir la clave `temperature` en los payloads del adaptador.
  - Quitar valores específicos por operación en llamadas de conversación, glue y búsqueda.
  - Mantener intactos los demás parámetros y funcionalidades del proveedor.
  - _Requirements: 1.1, 1.2_

- [x] 3. Retirar la configuración pública y validar la integración completa
- [x] 3.1 Eliminar opciones obsoletas del ejemplo de entorno
  - Quitar `LLM_TEMPERATURE` y `LLM_SKIP_TEMPERATURE` y sus comentarios de `.env.example`.
  - Confirmar que el `.env` local del usuario no se modifica.
  - _Requirements: 2.2, 2.3_

- [x] 3.2 Ejecutar y ajustar las pruebas de regresión
  - Actualizar tests de configuración y todas las pruebas afectadas por la retirada del argumento.
  - Ejecutar las pruebas unitarias e integración pertinentes y la suite completa.
  - Ejecutar Ruff (se reportan hallazgos preexistentes fuera del cambio) y verificar que no quedan referencias de runtime a la configuración retirada.
  - _Requirements: 3.1, 3.2_
