# Implementation Plan

## airi-conversacion-activa-llm

- [x] 1. Registro de sesiones y ciclo de vida por canal
  - Añadir el registro en memoria de sesiones de conversación por canal con los cuatro estados (Espectadora, Despertando, Activa, Retirada) y su información mínima de actividad/generación, sin persistencia ni dependencia de Discord.
  - Implementar recordación de actividad humana con incremento de generación y devolución de token para temporizadores.
  - Implementar apertura de despertar como transición compare-and-set desde Espectadora con validación de token; apertura fallida no muta ni lanza excepciones de control.
  - Implementar el cierre del despertar bajo la regla dura del dominio: la sesión solo se abre con texto publicado; la salida sin texto publicado limpia el despertar y arma el cooldown de espectador, sin importar la decisión de permanencia.
  - Implementar cierre de turno activo que mantiene la sesión o ejecuta la retirada (requiere publicación exitosa cuando hay respuesta); la retirada rearma el cooldown de cortesía de espectador y limpia el contexto efímero.
  - Implementar la retirada por inactividad validando estado, generación y plazo vigentes; la retirada deja la sesión en estado implícito de espectadora.
  - Cubrir con pruebas unitarias: transiciones válidas/inválidas, tokens desalineados que rechazan sin mutar, retiro a espectadora tras retirada, y reglas de cooldown en retirada y despertar silencioso.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.4, 3.5, 4.5, 5.1, 5.2_

- [x] 2. Contrato de salida estructurada de sesión
  - Definir el esquema estricto dedicado para la salida de la conversación de sesión, con tipos únicos (sin uniones cadena/nulo), decisión de permanencia obligatoria y silencio representado por cadena vacía.
  - Mantener intacto el contrato de salida de los turnos conversacionales normales y sus reglas de reparación de respuesta vacía.
  - Implementar el parseo normalizado de la salida de sesión con resultado de texto/silencio y decisión de permanencia; rechazar claves ausentes y tipos inválidos como fallo de contrato, nunca como silencio.
  - Cubrir con pruebas unitarias: cadena con texto, cadena vacía como silencio deliberado, decisión de permanencia, esquemas cerrados y compatibilidad del esquema normal.
  - _Requirements: 3.3, 3.6, 3.7_

- [x] 3. Contexto de modelo por modo de conversación
  - Extender el contexto del turno con el modo de conversación, el motivo de activación y la decisión de permanencia esperada, preservando los modos actuales.
  - Inyectar en el prompt del sistema la instrucción de estado conversacional: el modo espectador incluye motivo y captura pasiva; el modo activo pide evaluar el hilo de grupo y permite silencio mediante cadena vacía; el modo proactivo pide iniciar un tema sin fingir que alguien preguntó. Las instrucciones de estado viven solo en el mensaje de sistema, nunca en texto de usuario.
  - Asegurar el camino del silencio: la salida vacía deliberada no entra en el flujo de reparación de respuestas vacías, no publica y no muta afinidad, memorias, diario ni relación; produce igualmente resultado y traza con su decisión.
  - Evitar la publicación especial de tokens de silencio: sin marcadores literales ni texto visible del sentinel.
  - Cubrir con pruebas unitarias: composición del prompt por modo, existencia del camino de silencio sin reparación y ausencia de efectos de dominio en el turno silencioso.
  - _Requirements: 1.3, 1.4, 3.3, 3.4, 3.6, 3.7_

- [x] 4. Entrada por canal, estados de ruta y temporizadores
  - Conservar la precedencia actual de ruteo: autorización de canal, filtrado de bots y contenidos vacíos, comandos y actividad/cita; añadir la selección de ruta según el estado de sesión antes de las señales de espectador.
  - En espectadora, mantener el flujo vigente: captura al buffer pasivo, agrupación por debounce, evaluación de mención/entrega/tema/afinidad y despacho del turno de espectador con captura y motivo.
  - En activa (y en despertando, para no perder mensajes en vuelo), agrupar por debounce y encolar turnos de sesión sin añadir al buffer pasivo ni aplicar señales locales; los filtros de seguridad y la cola FIFO se mantienen.
  - Implementar los temporizadores asíncronos por canal con token: retiro por inactividad activa configurable y despertar proactivo configurable; cero deshabilita cada temporizador; la actividad humana rearma e invalida tareas anteriores.
  - Aplicar la invariante antispiral del proactivo: solo puede intentarse si la actividad humana es más reciente que la última tentativa; al consumir la ventana marca la tentativa; el modo espectador deshabilitado bloquea toda la feature.
  - Implementar la validación de cabeza de cola: cada trabajo al llegar a la cola FIFO revalida estado/generación; un trabajo de sesión cuyo canal ya no está activo se reclasifica por las señales locales de espectador con su propio contexto como detonante; el trabajo retirado o de temporizador con token obsoleto se descarta sin mutar.
  - Cubrir con pruebas unitarias e integración: rutas por estado, rearmed/invalidación, cero deshabilita, exactitud de expiración, tareas obsoletas inocuas y aislamiento entre canales.
  - _Requirements: 1.1, 1.2, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 4.5, 6.3_

- [x] 5. Despertar, publicación y transición a activa
  - Marcar la transición de despertar antes de ejecutar el turno de espectador y evitar despertares concurrentes por canal.
  - Publicar el texto del despertar y confirmar la transición a activa solo tras publicación exitosa y decisión positiva de permanencia; la retirada tras el primer texto sigue el camino de retirada con cooldown.
  - Aplicar la regla anti-bucle del despertar silencioso: sin texto publicado, aborta ignorando la permanencia, rearma el cooldown de espectador y marca la captura como consumida; la captura de un despertar fallido o silencioso devuelve el hilo a espectadora sin activar nada.
  - Consumir la captura y los detonantes del buffer solo después de publicar con éxito, adaptando la finalización actual del espectador a la confirmación de la transición.
  - Emitir el motivo de la transición en la observabilidad sin registrar contenidos ni identificadores de autores.
  - Cubrir con pruebas de integración: activación tras publicación, fallos de generación/publicación, despertar silencioso con anti-bucle y consumo correcto de la captura.
  - _Requirements: 1.2, 1.3, 1.5, 2.2, 2.3, 2.4, 3.5, 3.6, 6.2_

- [x] 6. Turnos activos, retirada y mensajes rezagados
  - Ejecutar turnos activos con todo el contexto acumulado por el debounce, sin exigir nuevas señales ni probabilidades; que la salida sea texto publicable o silencio permaneciendo activo.
  - Al decidir retirarse con texto, publicar primero la respuesta y solo después transicionar por retirada; al retirarse con silencio, no publicar nada y transicionar limpiamente.
  - Definir el comportamiento de la cola tras la retirada: no purgar; los jobs pendientes se revalidan y reclasifican al camino espectador; el cooldown rearmado impide el despertar inmediato por el hilo recién cerrado, con mención y entrega como únicas vías de rotura.
  - Al fallar la salida del modelo durante el modo activo, mantener el estado seguro previo y dejar el destino de retirada al temporizador local, sin inferir una retirada de una salida inválida.
  - Cubrir con pruebas de integración: permanencia, silencio activo, retirada con texto, retirada silenciosa, reclasificación de rezagados sin despertar inmediato y fallos de modelo.
  - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.7, 4.5, 5.1_

- [x] 7. Despertar proactivo e historial sintético
  - Encolar el turno proactivo por la misma cola FIFO con prioridad a la actividad humana: la ventana consumida produce a lo sumo una intervención por periodo de inactividad.
  - Usar el principal sintético de grupo sin efectos ligados a persona: sin afinidad, memorias, diario, romances ni acciones relacionales atribuidas; el texto publicado se agrega al historial canónico como entrada generada por el sistema.
  - Definir la entrada de historial del turno proactivo con metadatos vacíos estables y la marca de generación por sistema, y contrastar que los consumidores del historial (vista de inferencia, etiquetado de afinidad, usuarios conocidos, control de mixtura del turno rápido) la toleren sin errores ni falsas atribuciones.
  - Cubrir con pruebas unitarias e integración: una sola intervención por ventana, cancelación al entrar actividad humana, tolerancia del historial sintético por consumidores y aislamiento de rankings/afinidad.
  - _Requirements: 1.4, 4.2, 4.3, 6.1, 6.2_

- [x] 8. Cierre, observabilidad y verificación de extremo a extremo
  - Cancelar y esperar limpiamente las tareas de temporizador al cierre del cliente sin perder la despedida ni el comportamiento de apagado manual existente.
  - Emitir eventos de transición estructurados (estado previo/nuevo, motivo, generación) sin contenidos ni identificadores de autores; los eventos tuercen el detalle de la traza del turno ya existente sin duplicarla.
  - Verificar el aislamiento entre canales: sesiones y temporizadores por canal no se mezclan; el canal autorizado sigue siendo el único escenario de la feature.
  - Verificar el modo espectador deshabilitado mantiene exactamente el comportamiento conversacional normal y sus pruebas existentes verdes.
  - Cubrir con pruebas de integración: cierre del cliente con tareas pendientes, eventos de transición limpios y modo deshabilitado inerte.
  - _Requirements: 2.5, 4.4, 5.1, 5.2, 6.1, 6.2, 6.3, 6.4_
