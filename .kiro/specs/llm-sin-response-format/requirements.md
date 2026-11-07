# Requisitos

## Introducción

El cliente HTTP LLM debe dejar de enviar el campo `response_format` al backend. La aplicación continuará procesando las respuestas con sus parsers y normalizaciones deterministas, sin depender de restricciones de formato impuestas durante la generación.

## Requisitos

### Requisito 1: Peticiones al backend sin formato impuesto

**Objetivo:** Como operador de Airi, quiero que el cliente no envíe `response_format`, para usar el comportamiento de generación que ya funciona en mi backend.

#### Criterios de aceptación

1. WHEN el cliente envía una petición de chat THEN el cliente SHALL omitir la propiedad `response_format`, aunque la llamada reciba un esquema.
2. WHEN una llamada incluye herramientas y esquema THEN el cliente SHALL permitir construir la petición sin rechazarla por incompatibilidad con `response_format`.

### Requisito 2: Configuración sin variable obsoleta

**Objetivo:** Como operador, quiero que `LLM_RESPONSE_FORMAT` deje de formar parte de la configuración, para no mantener un control que ya no tiene efecto.

#### Criterios de aceptación

1. WHEN se consulten `.env` y `.env.example` THEN esos archivos SHALL no declarar `LLM_RESPONSE_FORMAT`.
2. WHEN se construya la configuración del cliente THEN `LlmConfig` SHALL no leer ni exponer `LLM_RESPONSE_FORMAT`.

### Requisito 3: Procesamiento robusto de respuestas

**Objetivo:** Como usuario de Airi, quiero que las respuestas sigan pasando por las normalizaciones existentes, para conservar los fallbacks deterministas sin formato estructurado del backend.

#### Criterios de aceptación

1. WHEN se recibe una respuesta del modelo THEN la aplicación SHALL mantener el parseo y la normalización deterministas existentes.
2. WHEN se ejecuten las pruebas del cliente y del procesamiento de salidas THEN las pruebas SHALL verificar que las peticiones omiten `response_format` y que los fallbacks existentes continúan funcionando.
