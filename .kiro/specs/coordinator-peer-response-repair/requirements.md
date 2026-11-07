# Requirements Document

## Project Description (Input)

Implementa una reparación de formato para las respuestas conversacionales entre bots gestionadas por el coordinador. Actualmente `src/airi/coordinator/worker.py:peer_reply` llama al LLM y espera JSON con la propiedad `reply` de tipo string; si `extract_json_object` no obtiene ese contrato lanza `ValueError` y el job queda `failed`. Reutilizar el patrón de reparación existente de `ConversationService` solo donde sea apropiado, manteniendo límites estrictos: una respuesta vacía válida debe poder representar silencio, presupuesto acotado (máximo una llamada de reparación), misma historia/persona, validación después de reparar y fallo seguro sin publicar contenido malformado. Añadir pruebas TDD para respuesta JSON inválida, recuperación exitosa, respuesta vacía/silencio y reparación fallida; conservar el comportamiento existente para una respuesta válida y no añadir reintentos de red.

## Introduction

Las respuestas entre Airi y Luna usan una llamada LLM coordinada separada del flujo conversacional habitual. Si el modelo no devuelve un objeto JSON con `reply` de tipo texto, el trabajo falla inmediatamente, aunque el sistema ya dispone de patrones de reparación de formato en otros flujos. Esta mejora permitirá recuperar una salida malformada con un único intento acotado, sin alterar una respuesta válida ni convertir un silencio voluntario en error.

## Requirements

### Requirement 1: Reparar una respuesta entre bots malformada
**Objective:** Como operador, quiero que el worker recupere una respuesta entre bots cuyo formato no se pueda analizar, para evitar fallos evitables del turno.

#### Acceptance Criteria
1. WHEN `peer_reply` recibe una salida primaria que no se puede extraer como objeto JSON con `reply` de tipo string THEN el worker SHALL realizar como máximo una llamada de reparación.
2. WHEN la salida primaria cumple el contrato THEN el worker SHALL publicar su `reply` sin realizar una llamada de reparación.
3. WHEN se solicita una reparación THEN el worker SHALL indicar al modelo que corrija únicamente el formato de la respuesta anterior y devuelva el objeto JSON requerido.
4. WHEN se solicita una reparación THEN el worker SHALL conservar la misma persona, historial y contexto conversacional utilizados en la llamada primaria.
5. WHEN la salida primaria contiene un objeto válido con `reply` como string vacío o compuesto solo por espacios THEN el worker SHALL tratarlo como silencio válido y SHALL NOT solicitar una reparación ni publicar un mensaje.

### Requirement 2: Validar y limitar la recuperación
**Objective:** Como mantenedor, quiero que la recuperación esté limitada y valide de nuevo el resultado, para no publicar contenido malformado ni introducir bucles de llamadas.

#### Acceptance Criteria
1. WHEN termina una llamada de reparación THEN el worker SHALL validar nuevamente que la salida sea un objeto JSON con `reply` de tipo string.
2. WHEN la reparación devuelve un `reply` string vacío o compuesto solo por espacios THEN el worker SHALL tratarlo como silencio válido sin publicar.
3. WHEN la reparación falla, no se puede analizar o no cumple el contrato THEN el worker SHALL marcar el trabajo como fallido y SHALL NOT publicar la salida primaria malformada ni la salida de reparación inválida.
4. WHILE una respuesta entre bots se procesa THE worker SHALL realizar como máximo una llamada de reparación, además de la llamada primaria.
5. WHEN falla una llamada LLM por un error de transporte THEN el worker SHALL conservar el comportamiento de error existente y SHALL NOT reintentar la llamada como si fuera un error de formato.

### Requirement 3: Compatibilidad y privacidad de diagnósticos
**Objective:** Como mantenedor, quiero conservar las respuestas válidas y evitar exponer contenido generado al diagnosticar fallos.

#### Acceptance Criteria
1. WHEN una respuesta válida no vacía es recibida THEN el worker SHALL publicarla usando el comportamiento actual, incluido el envío en fragmentos cuando sea necesario.
2. WHEN una respuesta de reparación válida no vacía es recibida THEN el worker SHALL publicar únicamente el texto de `reply` validado.
3. WHEN se registra un fallo de reparación THEN el worker SHALL registrar información suficiente para distinguir el fallo de reparación de un fallo de transporte, sin incluir el contenido bruto del prompt o de la respuesta del modelo.
4. The repair flow SHALL NOT add network retries or backoff to the LLM adapter.

### Requirement 4: Verificación automatizada
**Objective:** Como mantenedor, quiero pruebas deterministas del contrato de reparación para evitar regresiones.

#### Acceptance Criteria
1. WHEN la salida primaria es malformada y la reparación es válida THEN una prueba SHALL verificar que se envía exactamente una reparación y se publica la respuesta reparada.
2. WHEN la salida primaria es válida THEN una prueba SHALL verificar que se realiza una sola llamada y se conserva la publicación existente.
3. WHEN la salida primaria o reparada contiene `reply` vacío THEN una prueba SHALL verificar que no se publica texto y que el silencio no se considera formato inválido.
4. WHEN la reparación falla o devuelve un contrato inválido THEN una prueba SHALL verificar que el trabajo falla sin publicar contenido inválido y sin una segunda reparación.
5. WHEN la llamada primaria falla por transporte THEN una prueba SHALL verificar que no se realiza una reparación de formato.
