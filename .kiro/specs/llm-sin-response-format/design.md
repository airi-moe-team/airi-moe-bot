# Diseño: cliente LLM sin `response_format`

## Resumen

El adaptador HTTP de Airi dejará de adjuntar `response_format` a las peticiones Chat Completions. El parseo de la salida permanece en la capa de dominio (`llm_output.py`), que ya recupera JSON, normaliza campos y aplica fallbacks.

## Arquitectura

No se añaden componentes ni dependencias. El cambio elimina la configuración de transporte y simplifica el adaptador existente.

```mermaid
flowchart LR
  A[ConversationService] -->|schema como contexto interno| B[HttpLlmClient]
  B -->|messages y parámetros, sin response_format| C[Backend LLM]
  C -->|texto generado| D[parse_model_output]
  D --> E[ModelOutput normalizado]
```

## Decisiones

### Eliminar el soporte de transporte

- **Decisión:** retirar `response_format` de `LlmConfig`, `HttpLlmClient` y `build_llm`; el adaptador no emitirá esa propiedad.
- **Motivo:** el entorno operativo del usuario funciona con la opción desactivada y se desea retirar el control muerto.
- **Alternativa descartada:** conservar el parámetro con default `False`; mantendría una opción que ya no debe usarse y permitiría reactivarla accidentalmente.

### Conservar los esquemas y la validación de dominio

- **Decisión:** conservar los parsers y normalizadores de `llm_output.py`; los esquemas que se pasan internamente podrán seguir utilizándose por la lógica de reparación, pero no se serializan en la petición HTTP.
- **Motivo:** la aplicación debe continuar tolerando y saneando salidas del modelo sin depender de gramática del backend.

## Componentes e interfaces

- **`LlmConfig` / `build_llm`:** dejan de leer y propagar `LLM_RESPONSE_FORMAT`.
- **`HttpLlmClient`:** elimina el argumento y estado `response_format`; las llamadas `chat` y `chat_with_meta` continúan aceptando `schema` por compatibilidad de interfaz interna, pero no lo incorporan al payload.
- **Configuración de entorno:** eliminar la variable de `.env` y `.env.example`.
- **Pruebas:** verificar ausencia de `response_format` aun cuando se proporcione `schema`, cobertura de llamadas con herramientas y configuración sin la variable. Mantener pruebas existentes del parser.

## Errores y compatibilidad

El parseo continúa tratando JSON inválido mediante los fallbacks actuales. Desaparece el reintento de `json_schema` a `json_object`, porque ya no se intenta el modo estructurado. No se cambian los límites, normalizaciones ni comportamiento de las reparaciones de conversación.

## Estrategia de pruebas

1. Unitarias del adaptador: los payloads nunca incluyen `response_format` con o sin `schema`; herramientas y esquema no causan rechazo por incompatibilidad.
2. Configuración: `LlmConfig` y `build_llm` no exponen ni leen `LLM_RESPONSE_FORMAT`.
3. Regresión: ejecutar pruebas de parsing/sesión y pruebas de conversación relevantes para asegurar que los fallbacks actuales siguen operando.
