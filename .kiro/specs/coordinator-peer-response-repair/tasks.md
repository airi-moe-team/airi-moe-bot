# Implementation Plan

- [x] 1. Reparación de formato en `peer_reply`
- [x] 1.1 Escribir las pruebas del contrato (rojo)
  - Crear `tests/unit/test_worker_peer_repair.py` con `FakeLLM` y un canal que acumula envíos.
  - Cubrir: respuesta válida (una llamada), primaria inválida + reparación válida (dos llamadas), silencio en primaria, silencio tras reparar, doble inválida (dos llamadas, `ValueError`, sin envío), error de transporte sin reparación, y system prompt idéntico entre llamadas.
  - Verificar que la reparación añade el raw inválido como `assistant` y una instrucción `user`.
  - Ejecutar `.venv/bin/python -m pytest tests/unit/test_worker_peer_repair.py` y confirmar el rojo.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 1.2 Implementar helpers y reparación única (verde)
  - Extraer el prompt de sistema actual a un helper sin cambiar su texto.
  - Extraer la llamada LLM a un helper que reutilice el cliente y el esquema existentes.
  - Añadir `_parse_peer_reply` con la distinción `None` (inválido) frente a `""` (silencio válido).
  - Añadir `_repair_messages` y `PEER_REPAIR_PROMPT` para corregir solo el formato.
  - En `peer_reply`, abrir una sola sesión, reparar como máximo una vez, revalidar y fallar sin publicar si la reparación no cumple.
  - Mantener los errores de transporte sin capturar ni reintentar.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4_

- [x] 1.3 Verificar regresiones y calidad
  - Ejecutar `tests/unit/test_worker_peer_repair.py` y `tests/unit/test_worker_participation_decision.py`.
  - Ejecutar la suite completa de `tests/` si el tiempo lo permite.
  - Ejecutar `.venv/bin/ruff check src tests`.
  - Confirmar que no se añadieron reintentos de red ni cambios en `http_llm.py`.
  - _Requirements: 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_
