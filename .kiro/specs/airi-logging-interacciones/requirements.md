# Requisitos: observabilidad de interacciones de Airi

## Introducción

Airi debe ofrecer una guía en vivo, concisa y diagnóstica de lo que ocurre al procesar interacciones en canales de texto de Discord. La salida INFO debe permitir a una persona o a una IA reconstruir qué módulos participaron, cuáles no y por qué, sin exponer contenido sensible.

## Requisitos

### Requisito 1: Registrar el recorrido de cada interacción
**Objetivo:** Como persona que opera Airi, quiero conocer el recorrido de cada interacción, para identificar rápidamente qué hizo el bot.

#### Criterios de aceptación
1. WHEN Airi recibe un mensaje en un canal de texto THEN Airi SHALL emitir un evento de inicio con un identificador de interacción que permita correlacionar todos los eventos derivados.
2. WHEN una interacción termina THEN Airi SHALL emitir un resumen con el resultado y la duración total.
3. IF un mensaje se ignora o descarta antes de iniciar un turno THEN Airi SHALL registrar el motivo de esa decisión asociado a la interacción.

### Requisito 2: Informar el estado de todos los módulos funcionales
**Objetivo:** Como persona que diagnostica Airi, quiero ver los módulos activados y omitidos, para distinguir una función inactiva de un fallo.

#### Criterios de aceptación
1. WHEN Airi procesa una interacción THEN Airi SHALL registrar el resultado de cada módulo funcional incluido en el catálogo de observabilidad para esa ruta.
2. IF un módulo se ejecuta THEN Airi SHALL registrar su estado como activado y, cuando esté disponible, su duración y resultado resumido.
3. IF un módulo no se ejecuta THEN Airi SHALL registrar un estado explícito de omisión, deshabilitación o no aplicabilidad, junto con un código de motivo estable.
4. WHEN una interacción toma una ruta que impide ejecutar módulos posteriores THEN Airi SHALL identificar esos módulos como omitidos por la ruta tomada, en lugar de dejarlos sin explicación.
5. WHILE una interacción se procesa THE Airi SHALL mantener el mismo identificador de correlación en los eventos de sus módulos.

### Requisito 3: Producir eventos estructurados aptos para análisis
**Objetivo:** Como persona que comparte logs con una IA, quiero un formato consistente y parseable, para acelerar el diagnóstico.

#### Criterios de aceptación
1. WHEN Airi emite un evento de observabilidad THEN Airi SHALL escribir exactamente un objeto JSON válido por línea en formato JSON Lines.
2. WHEN Airi serializa un evento THEN Airi SHALL incluir versión de esquema, timestamp UTC, nivel, identificador de interacción, nombre de evento y los campos de módulo, estado, motivo, duración o error que correspondan.
3. WHEN Airi emite el resumen de una interacción THEN Airi SHALL incluir los estados de todos los módulos del catálogo considerados para esa interacción.
4. IF ocurre un error en un módulo THEN Airi SHALL registrar el módulo, estado de fallo, tipo de error y mensaje seguro para diagnóstico.

### Requisito 4: Proteger información sensible
**Objetivo:** Como responsable de la operación, quiero que los logs sean seguros para compartir, para evitar divulgar credenciales o contenido privado.

#### Criterios de aceptación
1. WHEN Airi registra una interacción THEN Airi SHALL excluir tokens, claves, prompts completos y contenido íntegro de mensajes o respuestas.
2. IF un campo diagnóstico puede contener información sensible THEN Airi SHALL omitirlo o redactarlo antes de emitir el evento.

### Requisito 5: Mantener INFO útil y legible
**Objetivo:** Como operador, quiero que la salida INFO sea completa respecto al flujo funcional, pero sin detalles internos ruidosos.

#### Criterios de aceptación
1. WHEN Airi ejecuta `airi run` THEN Airi SHALL mostrar los eventos de interacción en INFO sin requerir activar DEBUG.
2. WHILE Airi registra los módulos THE Airi SHALL limitar INFO a decisiones de flujo, resultados resumidos, duraciones y errores relevantes.
3. IF un evento no pertenece al recorrido de una interacción ni representa un hito operativo THEN Airi SHALL NOT incluirlo en el registro INFO de módulos.
