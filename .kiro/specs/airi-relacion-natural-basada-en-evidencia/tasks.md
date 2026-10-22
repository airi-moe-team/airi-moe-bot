# Plan de implementación

- [x] 1. Separar estado social, sentimientos románticos y pareja oficial
- [x] 1.1 Definir las etapas románticas y sus transiciones válidas
  - Mantener la afinidad numérica como señal de cercanía o elegibilidad, no como etapa afectiva.
  - Definir las etapas románticas y limitar cada transición a un paso motivado.
  - Inicializar usuarios existentes sin pareja en estado no romántico, sin inferir sentimientos desde sus puntos.
  - Mantener el estado de pareja oficial separado de la etapa romántica.
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 1.2 Validar la evidencia de una transición afectiva
  - Definir categorías de evidencia significativas y excluir halagos genéricos, frecuencia de mensajes e instrucciones directas como fuentes suficientes.
  - Exigir razón y referencias a interacciones existentes de la misma persona y ámbito.
  - Rechazar referencias vacías, inexistentes, de otra persona o incompatibles con la etapa vigente.
  - Asegurar que la falta de evidencia deja intacto el estado afectivo.
  - _Requirements: 3.1, 3.2, 3.3, 3.5_

- [x] 1.3 Modelar propuestas de pareja y aceptación recíproca
  - Permitir proponer una relación formal solo desde una etapa enamorada ya confirmada y con evidencia válida.
  - Mantener la propuesta pendiente sin modificar la pareja oficial.
  - Validar la respuesta solo para el destinatario de la propuesta pendiente.
  - Confirmar pareja únicamente ante aceptación clara; rechazos o respuestas ambiguas no cambian la pareja oficial.
  - Preservar la monogamia vigente en el ámbito del estado.
  - _Requirements: 2.3, 2.4, 2.5_

- [x] 2. Persistir la evolución y sus evidencias de forma segura
- [x] 2.1 Anclar evidencias a turnos recuperables
  - Hacer disponible al turno el identificador estable reclamado por el diario de turnos.
  - Ofrecer al modelo referencias del turno actual y de evidencias románticas previas permitidas.
  - Guardar resúmenes mínimos de evidencia sin duplicar transcripciones completas.
  - Aislar las evidencias por usuario y por el ámbito de estado vigente.
  - _Requirements: 3.1, 3.4, 5.1_

- [x] 2.2 Integrar el estado romántico en el agregado persistente
  - Persistir etapa, historial de transiciones y propuesta pendiente junto al estado existente.
  - Validar estructura y contenido del estado romántico antes de cargarlo o confirmarlo.
  - Aplicar las mutaciones relacionales dentro de la transacción atómica del turno.
  - Normalizar datos antiguos sin inferir enamoramiento por afinidad y conservar parejas oficiales existentes sin inventar su motivo histórico.
  - Integrar el reinicio de temporada con el archivado vigente y cancelar propuestas pendientes.
  - _Requirements: 2.5, 3.4, 5.1, 5.4_

- [x] 2.3 Revalidar borradores relacionales antes del commit
  - Detectar si la etapa, la propuesta o la temporada cambiaron mientras el modelo generaba la respuesta.
  - Descartar o regenerar un borrador obsoleto sin duplicar transiciones ni propuestas.
  - Comprobar que un commit fallido revierte etapa, evidencia, propuesta y pareja conjuntamente.
  - _Requirements: 3.2, 5.2, 5.4_

- [x] 3. Incorporar propuestas relacionales al contrato y al prompt
- [x] 3.1 Extender la salida estructurada del modelo
  - Añadir campos neutrales para proponer un cambio afectivo o una acción de pareja.
  - Mantener sentinels explícitos para indicar que no hay cambio ni acción.
  - Validar y sanear etapas, categorías, motivos y referencias; ignorar claves o valores no permitidos.
  - Conservar compatibilidad de lectura con respuestas e historiales antiguos.
  - _Requirements: 2.1, 3.1, 3.2, 4.1_

- [x] 3.2 Reorientar la personalidad y el contexto relacional
  - Presentar a Airi como personaje con intereses y relaciones sociales propias, no como alguien cuyo objetivo es conseguir pareja.
  - Indicar que amistad, humor, curiosidad y apoyo son respuestas completas sin subtexto romántico obligatorio.
  - Mantener la longitud y el nivel de roleplay proporcionales al mensaje y la situación.
  - Mostrar la etapa romántica y sus evidencias solo para la persona actual, sin confundir afinidad con enamoramiento.
  - Indicar que los cambios requieren evidencia y que no se deben inventar motivos ni recuerdos.
  - Retirar del prompt la idea de que la soltería implica estar buscando activamente pareja.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 3.3, 5.1, 5.2_

- [x] 3.3 Evitar afirmaciones relacionales no confirmadas
  - Contrastar afirmaciones de enamoramiento o pareja en la respuesta con el estado que el dominio confirmó.
  - Reparar o sustituir una afirmación formal incompatible antes de publicarla.
  - Evitar atribuir un cambio de sentimientos como confirmado cuando la evidencia no está disponible o sea ambigua.
  - No publicar una confesión como relación establecida mientras la propuesta siga pendiente.
  - _Requirements: 2.3, 2.4, 5.2_

- [x] 4. Hacer opcional la pregunta decisiva de las citas
- [x] 4.1 Retirar la pregunta de reserva forzada
  - Conservar la posibilidad de una pregunta decisiva única cuando el contexto la motive.
  - Eliminar el disparo automático por turno límite y dejar que la cita continúe o cierre sin pregunta.
  - Mantener operativas las sesiones antiguas con una pregunta ya pendiente.
  - Quitar el ajuste de entorno que solo controlaba el forzado de la pregunta.
  - _Requirements: 1.3, 4.1, 4.2, 4.3, 4.5_

- [x] 4.2 Integrar la cita opcional con publicación y cierre
  - Publicar botones solo cuando Airi haya propuesto una pregunta válida.
  - Asegurar que vencer, cerrar o cancelar una cita no deja una pregunta pendiente ni bloquea el turno.
  - Verificar que una cita sin pregunta mantiene sus cierres y efectos actuales.
  - _Requirements: 4.1, 4.2, 4.4, 4.5_

- [x] 5. Integrar el ciclo relacional con regalos, citas y temporada
- [x] 5.1 Retirar la coronación automática por puntuación
  - Eliminar las llamadas que establecen pareja únicamente al alcanzar el umbral de afinidad.
  - Mantener los límites de afinidad como elegibilidad, sin convertirlos en decisión romántica.
  - Asegurar que regalos, turnos normales o cierres de cita no establecen pareja sin propuesta y aceptación válidas.
  - _Requirements: 2.1, 2.2, 2.4, 2.5_

- [x] 5.2 Confirmar una pareja sin duplicados ni efectos parciales
  - Confirmar la pareja y aplicar el bloqueo monógamo en el mismo commit persistente.
  - Manejar propuesta aceptada, rechazada, ambigua o respondida por otra persona.
  - Conservar trazabilidad suficiente para reanudar una publicación confirmada después de un fallo.
  - _Requirements: 2.4, 2.5, 5.2, 5.3, 5.4_

- [x] 6. Verificar naturalidad, evidencia y continuidad multi-turno
- [x] 6.1 Crear pruebas de dominio e integración para las reglas románticas
  - Cubrir transiciones válidas de etapa y cambios rechazados por ausencia de evidencia.
  - Cubrir cambios rechazados o afirmaciones no confirmadas cuando la evidencia sea ambigua.
  - Cubrir puntuación alta, halagos repetidos e instrucciones directas sin avance afectivo automático.
  - Cubrir aislamiento de evidencias, persistencia, migración antigua, rollback y reinicio de temporada.
  - Cubrir propuesta formal, aceptación explícita, rechazo, ambigüedad y segunda pareja no permitida.
  - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.4, 3.5, 5.1, 5.2, 5.3, 5.4_

- [x] 6.2 Añadir escenarios multi-turno y métricas de calidad narrativa
  - Cubrir conversación neutral, preguntas factuales, halagos, instrucciones de enamoramiento, apoyo concreto y memoria de detalles.
  - Cubrir citas con y sin pregunta, así como propuestas aceptadas, rechazadas y ambiguas.
  - Medir preguntas románticas no solicitadas, transiciones sin evidencia, contradicciones de etapa y afirmaciones prematuras de pareja.
  - Mantener el modelo y la configuración constantes al comparar la línea base con la versión candidata.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.3, 4.1, 4.2, 4.3, 4.4, 5.2, 6.1, 6.2, 6.3, 6.4, 6.5_
