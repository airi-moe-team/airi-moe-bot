# Diseño técnico: voz de Airi sin sesgo de asistente

## Overview

El cambio refina las instrucciones de personalidad existentes en `src/airi/domain/prompts.py`; no añade componentes de runtime ni dependencias. El objetivo es que respeto y ayuda no se expresen como una capa obligatoria de cortesía, validación, calidez o disponibilidad, y que la respuesta pueda ser neutral, directa, discrepante o seca según el contexto.

Se preservan la identidad canónica, las reglas de afinidad y relación, el contrato JSON, el esquema y el procesamiento del output. La intervención se limita a texto del prompt y pruebas unitarias de construcción del prompt.

### Goals
- Eliminar formulaciones globales que inducen cercanía o cordialidad automática.
- Hacer que el afecto y la calidez dependan del contexto y el vínculo, sin borrar la capacidad de expresarlos.
- Evitar ejemplos de salida que presenten aprobación automática como comportamiento predeterminado.
- Mantener el prompt completo y compacto alineados y verificarlo con tests.

### Non-Goals
- Cambiar el esquema de respuesta, enums, validadores o lógica de relaciones/afinidad.
- Hacer a Airi hostil, irrespetuosa o sistemáticamente seca.
- Modificar modelos, parámetros de inferencia o comportamiento fuera de las instrucciones del prompt.

## Architecture

### Existing Architecture Analysis
`src/airi/domain/prompts.py` contiene los bloques constantes del prompt, las variantes completa/compacta, las instrucciones dinámicas de afinidad y los contratos de salida. `build_system_prompt` ensambla estos bloques. La arquitectura es texto de dominio puro, sin dependencias externas. Las pruebas relevantes residen en `tests/unit/test_system_prompt_naturalness.py` y `tests/unit/test_prompt_variants.py`.

Los cambios de trabajo existentes en esos archivos se consideran ajenos a esta feature y deben conservarse; la implementación editará solo las frases necesarias sobre el estado actual del árbol.

### High-Level Architecture

No se introducen componentes nuevos. Se ajustan instrucciones existentes:

- `SYSTEM_PROMPT`: tono base y conducta conversacional.
- `AFFINITY_TONE_HINTS` / `affinity_prompt_section`: trato por nivel de vínculo.
- `OUTPUT_CONTRACT_PROMPT` y `COMPACT_OUTPUT_PROMPT`: pauta de respuesta y ejemplos, preservando estructura y campos.
- Pruebas unitarias: inspección del texto ensamblado y de las invariantes del esquema.

## Technology Alignment and Design Decisions

Se mantiene Python y el patrón actual de constantes/compositores de prompt en el dominio. No se agregan dependencias, configuraciones ni migraciones.

### Decisiones

1. **La autonomía se expresa mediante instrucciones contextuales, no prohibiciones absolutas.** Esto reduce la cortesía automática sin bloquear respuestas respetuosas, cálidas o de apoyo cuando encajen.
2. **La guía base y las guías dinámicas se ajustan de manera coordinada.** Evita que el nivel de afinidad vuelva a imponer cordialidad o calidez que el tono base deja de exigir.
3. **El contrato y los ejemplos cambian solo en contenido lingüístico.** No se alteran nombres de campos, tipos, enums, validación ni formato JSON.

## Components and Interfaces

### Dominio de prompts — `src/airi/domain/prompts.py`

**Responsabilidad:** ensamblar personalidad, contexto relacional y contrato de salida para el LLM.

**Modificación:** sustituir instrucciones que impliquen trato cordial/cercano por defecto por guía neutral y contextual; aclarar que no debe validar, agradecer, tranquilizar ni ofrecer ayuda por reflejo. Mantener la libertad de disentir y los límites de Airi. Ajustar las indicaciones dinámicas por afinidad y aclarar que `warmth` representa el ánimo del turno, no una obligación de tono social. Usar ejemplos neutrales en los formatos completo y compacto.

**Invariantes:** `build_system_prompt` mantiene sus firmas y composición; los campos y esquemas de salida permanecen idénticos. `compact=True` y la variante actual no deben reintroducir la directiva retirada.

### Pruebas unitarias

Añadir o adaptar pruebas en los módulos existentes para verificar el prompt ensamblado completo y compacto: presencia de la regla de no complacencia automática, trato condicionado por contexto, ausencia de formulaciones de cordialidad obligatoria y conservación de claves/valores del contrato JSON.

## Testing Strategy

- **Unitarias de naturalidad:** comprobar las instrucciones base y que las respuestas puedan ser neutrales/directas sin trato servicial predeterminado.
- **Unitarias de variantes:** verificar coherencia entre prompt completo y compacto y que ejemplos/instrucciones de ambos eviten aprobación automática.
- **Regresión del contrato:** comparar claves, enums y estructura de salida antes/después; sin cambios funcionales esperados.
- Ejecutar los tests focalizados y luego el conjunto unitario relacionado con prompts; evitar fixtures de conversación no relacionados.

## Risks and Mitigations

- **Sobreajuste hacia sequedad u hostilidad:** formular la regla como ausencia de obligación automática, conservando respeto y calidez contextual; cubrirlo en tests.
- **Directivas contradictorias entre secciones:** revisar los prompts ya ensamblados en ambos modos y cubrir explícitamente el contenido dinámico de afinidad.
- **Interferencia con cambios locales previos:** limitar el diff a líneas propias de esta feature y revisar el diff respecto al estado inicial antes de validar.
