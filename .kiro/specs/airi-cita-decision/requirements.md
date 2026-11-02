# Documento de requisitos

## Introducción

El flujo de citas permitirá que cualquier usuario invite a Airi sin exigir un nivel mínimo de afinidad. La invitación no iniciará una cita automáticamente: Airi valorará si quiere aceptar según la relación y el contexto disponibles, y podrá aceptar o rechazar independientemente del rango de afinidad. Así, la cita será una decisión de Airi y conservará sus consecuencias emocionales y de afinidad, tanto positivas como negativas.

## Requisitos

### Requisito 1: Solicitar una cita sin umbral de afinidad
**Objetivo:** Como usuario, quiero poder invitar a Airi a una cita con cualquier afinidad, para que la posibilidad de invitarla no dependa de alcanzar un nivel prefijado.

#### Criterios de aceptación
1. WHEN un usuario elegible ejecuta `!cita` THEN el sistema SHALL permitir que la invitación sea evaluada sin exigir un mínimo de puntos o nivel de afinidad.
2. WHEN se acepta o rechaza una invitación THEN el sistema SHALL conservar las restricciones independientes de cooldown, cita activa y relación/pareja que ya aplican al usuario.

### Requisito 2: Decisión autónoma de Airi
**Objetivo:** Como usuario, quiero que Airi decida si acepta mi invitación, para que iniciar una cita refleje su disposición y no sea automático.

#### Criterios de aceptación
1. WHEN Airi recibe una invitación elegible THEN el sistema SHALL evaluar si acepta o rechaza antes de mostrar el selector de escenas y antes de crear una sesión de cita.
2. WHEN Airi evalúa una invitación THEN el sistema SHALL considerar la afinidad como contexto, pero SHALL NOT usar un umbral fijo de afinidad como condición necesaria o suficiente para aceptar.
3. WHEN la afinidad es baja o alta THEN el sistema SHALL permitir que Airi acepte o rechace según su evaluación, sin imponer un resultado predeterminado por el rango.
4. WHEN Airi acepta la invitación THEN el sistema SHALL comunicar la aceptación y mostrar el flujo actual de selección de escena.
5. WHEN Airi rechaza la invitación THEN el sistema SHALL comunicar el rechazo de forma coherente con su relación y contexto actuales, sin mostrar el selector de escenas ni iniciar una cita.
6. IF el sistema no puede obtener una decisión válida THEN el sistema SHALL informar que no pudo procesar la invitación y SHALL NOT crear una sesión de cita ni consumir el cooldown.

### Requisito 3: Efectos de la decisión y continuidad de la cita
**Objetivo:** Como usuario, quiero que una invitación rechazada no cambie mi estado y que una cita aceptada conserve sus consecuencias, para que el resultado sea claro y consistente.

#### Criterios de aceptación
1. WHEN Airi rechaza una invitación THEN el sistema SHALL NOT crear ni persistir una sesión de cita, actualizar la marca de última cita, consumir el cooldown ni alterar la afinidad.
2. WHEN Airi acepta una invitación y el usuario selecciona una escena THEN el sistema SHALL iniciar la cita y registrar el cooldown conforme al flujo existente.
3. WHILE una cita aceptada está en curso THE sistema SHALL conservar las reglas existentes que permiten cambios positivos o negativos significativos de afinidad y el cierre según el desenlace.
4. WHEN se evalúa o inicia una invitación THEN el sistema SHALL conservar la exclusividad de una cita activa y las reglas actuales para usuarios bloqueados por la relación/pareja.

### Requisito 4: Verificabilidad del flujo
**Objetivo:** Como mantenedor, quiero pruebas que cubran aceptación, rechazo y restricciones existentes, para evitar regresiones en el flujo de citas.

#### Criterios de aceptación
1. WHEN se prueba la decisión en rangos bajos y altos de afinidad THEN las pruebas SHALL verificar que tanto aceptar como rechazar son resultados posibles en cada rango.
2. WHEN se prueba un rechazo THEN las pruebas SHALL verificar que no se crea sesión, no se cambia afinidad, no se actualiza la última cita y no se consume cooldown.
3. WHEN se prueba una aceptación THEN las pruebas SHALL verificar que el selector precede al inicio efectivo y que la cita solo se crea tras elegir una escena.
4. WHEN se prueban cooldown, cita activa y reglas de relación/pareja THEN las pruebas SHALL verificar que dichas restricciones se mantienen independientemente de la afinidad.
