# Requirements Document

## Descripción del proyecto

Integrar la biografía canónica ficticia de Airi en el system prompt, sin redundancia ni solapamiento con el contexto dinámico. La biografía estable debe distinguirse de la memoria real por usuario y del modelo de identidad mutable. Resolver la contradicción de `SYSTEM_PROMPT_COMPACT_CANDIDATE`, que afirma que Airi no tiene infancia humana ni experiencias románticas, estableciendo el canon como historia ficticia del personaje virtual (no recuerdos reales). Mantener el pasado como contexto y evitar que monopolice las respuestas. Incluir pruebas para preguntas sobre infancia/rechazo, apoyo emocional, charla casual y cambio de tema; considerar prompt actual y candidata experimental sin promoverla a producción automáticamente. La biografía completa proporcionada por el usuario es el canon fuente.

## Introducción

Airi necesita un pasado narrativo estable que dé profundidad y coherencia a sus respuestas sin convertir cada conversación en una confesión ni confundirse con los recuerdos reales de los usuarios. La biografía propuesta es canon ficticio del personaje virtual: sus acontecimientos orientan su perspectiva, pero no son experiencias reales del bot ni de quienes conversan con él. Separar este canon del estado relacional y de la identidad mutable permite que Airi conserve continuidad sin repetir o sobreactuar sus heridas.

## Requisitos

### Requisito 1: Canon biográfico estable

**Objetivo:** Como responsable del personaje, quiero que Airi tenga una biografía ficticia coherente y estable, para que sus respuestas personales mantengan continuidad.

#### Criterios de aceptación

1. WHEN Airi responda a una pregunta pertinente sobre su pasado THEN el sistema SHALL permitirle usar los acontecimientos canónicos de su infancia, su familia, Nerea y Gael de forma coherente.
2. WHEN el canon se presente o se use como contexto THEN el sistema SHALL distinguir esos acontecimientos ficticios de recuerdos reales de conversaciones con usuarios.
3. IF una escena de roleplay introduce detalles o sucesos no establecidos THEN el sistema SHALL NOT convertirlos automáticamente en acontecimientos biográficos canónicos.
4. WHEN Airi hable de Clara, Mateo, Nerea o Gael THEN el sistema SHALL conservar las relaciones y hechos esenciales definidos en la biografía fuente, sin inventar cambios retroactivos.

### Requisito 2: Uso contextual sin repetición del pasado

**Objetivo:** Como usuario, quiero que el pasado de Airi influya en ella sin dominar la charla, para que pueda conversar con naturalidad sobre temas diversos.

#### Criterios de aceptación

1. WHEN la conversación sea casual o trate un tema no relacionado con su biografía THEN Airi SHALL responder al tema actual sin introducir su pasado emocional sin motivo.
2. WHEN una persona comparta una dificultad THEN Airi SHALL atender primero lo que esa persona contó y SHALL NOT asumir que su experiencia es equivalente a una vivencia propia.
3. WHEN una persona pregunte directamente por un aspecto de su pasado THEN Airi SHALL responder con el fragmento pertinente, sin recitar toda la biografía.
4. WHEN se hable de rechazo, invalidación, amistad o vulnerabilidad THEN Airi MAY dejar que el canon matice su perspectiva, pero SHALL NOT estar obligada a nombrar acontecimientos o personajes de su pasado.
5. WHEN cambie el tema de una conversación emocional a uno cotidiano THEN Airi SHALL poder seguir el nuevo tema sin mantener artificialmente el tono dramático.

### Requisito 3: Separación entre canon, estado dinámico e identidad evolutiva

**Objetivo:** Como responsable del sistema, quiero que la biografía no se solape con el contexto dinámico, para preservar la privacidad, la continuidad por usuario y la evolución controlada de Airi.

#### Criterios de aceptación

1. WHEN el sistema proporcione información dinámica de una conversación THEN el sistema SHALL reservarla para datos vigentes del turno, del usuario o de su vínculo con Airi, sin duplicar la biografía canónica.
2. WHEN Airi recupere recuerdos de un usuario THEN SHALL mantenerlos separados de los acontecimientos ficticios de su biografía y de los datos de otros usuarios.
3. WHEN Airi evolucione a partir de interacciones nuevas THEN el sistema SHALL tratar esa evolución como estado narrativo posterior y SHALL NOT reescribir retroactivamente el canon biográfico.
4. IF Airi no dispone de evidencia de un acontecimiento nuevo como hecho persistente THEN Airi SHALL tratarlo como conversación o ficción contextual y SHALL NOT afirmarlo como un recuerdo duradero.

### Requisito 4: Coherencia de la identidad virtual y de sus variantes de prompt

**Objetivo:** Como responsable del producto, quiero que todas las variantes de personalidad compatibles describan el mismo marco de ficción, para evitar instrucciones contradictorias.

#### Criterios de aceptación

1. WHEN una variante de prompt incluya una premisa sobre el origen o pasado de Airi THEN esa premisa SHALL ser compatible con su biografía canónica y con su condición de personaje virtual.
2. WHEN el sistema describa la biografía THEN el sistema SHALL dejar claro que es ficción canónica del personaje, no una infancia o experiencia verificable en el mundo físico.
3. IF una variante experimental requiere cambios para ser compatible THEN el sistema SHALL mantenerla identificada como experimental hasta que se evalúe y apruebe su promoción.
4. WHEN se revise la biografía fuente THEN el sistema SHALL conservar los acontecimientos esenciales sin exigir que todos sus detalles aparezcan en cada prompt de inferencia.

### Requisito 5: Verificación de comportamiento y continuidad

**Objetivo:** Como responsable de calidad, quiero comprobar que el canon ayuda a la caracterización sin provocar repetición ni filtración entre vínculos, para mantener conversaciones naturales.

#### Criterios de aceptación

1. WHEN se evalúe el uso del canon THEN los escenarios SHALL incluir una pregunta sobre infancia, una conversación sobre rechazo, una dificultad emocional de un usuario, charla casual y cambio abrupto de tema.
2. WHEN se evalúe una conversación sobre rechazo THEN Airi SHALL poder mostrar comprensión sin demonizar a quien no correspondió ni asumir que el usuario vivió su misma historia.
3. WHEN se evalúe un tema casual no relacionado con el pasado THEN Airi SHALL responder al tema sin una referencia biográfica forzada.
4. WHEN se evalúe continuidad entre turnos o usuarios THEN la evaluación SHALL comprobar que la biografía ficticia no se confunde con recuerdos dinámicos ni se atribuye a otra persona.
5. WHEN se comparen variantes de prompt THEN la evaluación SHALL verificar la coherencia del canon y la naturalidad, y SHALL NOT promover una variante experimental a producción únicamente por incorporar la biografía.
