# Plan de implementación revisado

- [x] 1. Aplicar la declaración automáticamente solo en llamadas elegibles de llama.cpp
- [x] 1.1 Fijar con pruebas la nueva elegibilidad y la preservación del payload
  - Comprobar la declaración de `get_datetime` y `tool_choice="none"` en llamadas llama con y sin respuesta JSON estructurada.
  - Comprobar que mensajes, límites, thinking y demás campos mantienen sus valores.
  - Comprobar que proveedores distintos de llama, herramientas reales y choice explícito no reciben la declaración.
  - Verificar que un valor residual de la antigua variable no cambia los requests.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 3.1, 3.2, 3.3, 3.4_

- [x] 1.2 Eliminar la configuración de producción e integrar la elegibilidad automática
  - Eliminar la lectura de la variable y su propagación en la construcción del cliente.
  - Aplicar la declaración a las llamadas JSON normales de llama, sin cambiar otros proveedores ni tools reales.
  - Conservar el estado real de aplicación en la traza por llamada y la capacidad de evaluación aislada de la ruta anterior.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 3.4_

- [x] 2. Proteger el contrato de respuesta en todos los caminos elegibles
- [x] 2.1 Cubrir anomalías y procesamiento no streaming
  - Simular tool calls sintéticas inesperadas y comprobar que no se ejecutan ni se entregan a consumidores.
  - Verificar que contenido, razonamiento, uso y finish reason se mantienen y que el logging no guarda argumentos sensibles.
  - Comprobar que tools reales siguen su normalización habitual y que el error HTTP conserva la ruta segura existente.
  - _Requirements: 2.2, 2.3, 2.4, 3.5, 4.1, 4.3, 4.4_

- [x] 2.2 Cubrir streaming, JSON y recuperación conversacional
  - Verificar ensamblado SSE y descarte de deltas de tool calls sintéticas, sin admitir tools reales en streaming.
  - Verificar JSON válido e inválido con schema/strict_schema, parser y reparaciones sin perder respuesta visible.
  - Cubrir respuestas vacías, finish reasons, errores y metadatos de primer token/contenido.
  - _Requirements: 3.4, 3.5, 4.1, 4.2, 4.3, 4.4_

- [x] 3. Garantizar que la evaluación mida solicitudes realmente optimizadas
- [x] 3.1 Corregir las pruebas y el benchmark A/B aislado
  - Comparar peticiones con iguales mensajes, schema/strict_schema y parámetros; activar/desactivar la declaración solo en el harness.
  - Rechazar un resultado ON si la llamada principal no declaró la herramienta realmente.
  - Mantener métricas seguras por llamada y persistencia de registros sensibles solo bajo opción explícita.
  - _Requirements: 5.1, 5.2, 5.3, 5.5_

- [x] 3.2 Probar integración y escenarios de evaluación
  - Confirmar con pruebas de integración que el flujo real de saludo utiliza la declaración y sigue produciendo JSON válido y respuesta visible.
  - Conservar escenarios representativos y al menos cinco repeticiones por modo para una evaluación ampliada posterior; no inferir estabilidad de un único par.
  - Registrar aparte los resultados del piloto ya ejecutado y sus limitaciones; no lanzar otro benchmark live automáticamente.
  - _Requirements: 3.4, 4.4, 5.3, 5.4, 5.5_

- [x] 4. Integrar y verificar la solución completa
- [x] 4.1 Ejecutar pruebas unitarias, de integración y regresión relacionadas
  - Confirmar el comportamiento integrado de llama sin variable de entorno y la no regresión de otros proveedores.
  - Comprobar parser, streaming, reintentos y trazas seguras; corregir fallos de la suite antes de cerrar.
  - _Requirements: 1.1, 1.2, 1.3, 2.2, 3.4, 4.1, 4.2, 4.4, 5.1_
