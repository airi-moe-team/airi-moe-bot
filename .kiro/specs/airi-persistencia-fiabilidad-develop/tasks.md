# Implementation Plan

- [x] 1. Definir el contrato del estado canónico y las reglas de validación
- [x] 1.1 Establecer el esquema del estado agregado
  - Definir los campos obligatorios y sus tipos: mundo, afinidad, citas, memorias, diario, usuarios, historiales, registro de turnos y metadatos
  - Distinguir el contador de versión de dominio de la versión de esquema
  - Validar que los booleanos no se acepten como enteros y que una versión de esquema futura se rechace
  - Definir la validación específica de cada conjunto heredado (objetos y diario como lista)
  - Escribir primero las pruebas de esquema válido, claves ausentes, tipos incorrectos y versiones incompatibles
  - _Requirements: 1.2, 2.1, 6.2_

- [x] 1.2 Definir los contratos de turno y la huella de la cita
  - Modelar los estados processing, committed, published y failed, y sus transiciones permitidas
  - Definir la clave estable del turno y el índice de todos los mensajes que contribuyen a un lote
  - Definir el borrador inmutable de turno y el resultado aplicado, incluyendo respuesta, GIF, avisos y traza
  - Calcular la huella de una cita a partir de su escena y momento de inicio, sin añadir un identificador nuevo al esquema de citas
  - Escribir pruebas de claves, huellas, inmutabilidad y transiciones inválidas
  - _Requirements: 4.2, 4.3, 5.2_

- [x] 1.3 Validar que un turno generado siga siendo aplicable
  - Detectar que la cita cambió de escena, se cerró o fue reemplazada durante la generación
  - Detectar que la temporada cambió durante la generación
  - Devolver una decisión explícita sin mutar el estado
  - Escribir pruebas de turno válido, cita reemplazada, cita cerrada y temporada cambiada
  - _Requirements: 5.2, 3.5_

- [x] 2. Implementar el almacén atómico del estado
- [x] 2.1 Guardar el estado de forma atómica y con copia recuperable
  - Validar antes de tocar el sistema de archivos
  - Escribir en un archivo temporal, sincronizar el contenido y reemplazar el activo de forma atómica
  - Rotar una copia de recuperación solo si el activo anterior era válido
  - Sincronizar el directorio después del reemplazo, con tolerancia a fallos del sistema
  - Escribir pruebas que inyecten fallos en cada paso y comprueben que el estado anterior queda intacto
  - _Requirements: 1.1, 1.3, 1.5_

- [x] 2.2 Cargar, recuperar y aislar estado corrupto
  - Distinguir archivo ausente, archivo inválido, archivo bloqueado y error de E/S
  - Copiar el estado inválido a cuarentena antes de intentar recuperarlo
  - Restaurar desde la copia válida e informar que hubo recuperación
  - Bloquear el arranque si ni el activo ni la copia son válidos, sin sustituirlos por valores por defecto
  - Escribir pruebas de recuperación, cuarentena, doble corrupción y archivo ausente en primera instalación
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 2.3 Impedir que dos procesos escriban el mismo estado
  - Adquirir un bloqueo exclusivo no bloqueante sobre el archivo de instancia
  - Registrar el proceso propietario y liberar el bloqueo al apagar o fallar el arranque
  - Informar con claridad cuando otra instancia ya está activa
  - Escribir pruebas de segunda adquisición, liberación y reutilización del bloqueo
  - _Requirements: 5.4_

- [x] 2.4 Configurar rutas, copias y retención operativa
  - Añadir la configuración de directorio de datos, límite de copias, número de temporadas archivadas y vigencia de publicaciones pendientes
  - Establecer valores por defecto conservadores sin dependencias nuevas
  - Excluir del control de versiones los artefactos operativos y datos personales nuevos
  - Escribir pruebas de configuración por defecto, variables de entorno y valores inválidos
  - _Requirements: 7.2, 7.3_

- [x] 3. Integrar la persistencia transaccional y la migración
- [x] 3.1 Implementar la fachada de persistencia sobre el estado en memoria
  - Conectar cada solicitud de guardado con una escritura del agregado completo
  - Agrupar varias solicitudes dentro de una transacción y persistir una sola vez al confirmar
  - Restaurar la instantánea en memoria si la transacción o la escritura fallan
  - Distinguir commits de dominio de commits de metadatos sin alterar la versión de dominio
  - Garantizar que ninguna transacción cruce una espera de red ni se ejecute fuera del bloqueo de commit
  - Escribir pruebas de guardado inmediato, coalescencia, rollback y versiones
  - _Requirements: 1.1, 1.3, 1.5, 3.1, 3.5, 5.1_

- [x] 3.2 Migrar los archivos heredados de forma segura e idempotente
  - Detectar la ausencia de estado canónico y la presencia total o parcial de los archivos heredados
  - Copiar todos los archivos de origen antes de construir el estado nuevo
  - Validar cada conjunto, componer el agregado y validar el resultado completo
  - Activar el nuevo estado solo después de una escritura temporal y validación correctas
  - Registrar una huella del origen para no repetir la migración ni duplicar datos
  - Bloquear ante archivos parciales, ilegibles o ambiguos, conservándolos en cuarentena y sin inventar valores
  - Escribir pruebas de migración completa, idempotencia, archivo ausente, archivo parcial y corrupción
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 2.4_

- [x] 3.3 Conectar el arranque con carga, migración y recuperación
  - Adquirir el bloqueo de instancia antes de leer o escribir estado
  - Cargar el estado canónico o ejecutar la migración cuando corresponda
  - Construir el estado en memoria desde el agregado y conectar todos los callbacks de guardado
  - Liberar el bloqueo de instancia en el apagado y ante errores de arranque
  - Producir un mensaje operativo único con rutas de copia y cuarentena cuando el arranque se bloquee
  - Escribir pruebas de arranque nuevo, arranque migrado, recuperación y bloqueo seguro
  - _Requirements: 1.4, 2.2, 2.3, 2.5, 5.4, 6.5_

- [x] 3.4 Añadir diagnóstico de almacenamiento sin exponer datos privados
  - Exponer ruta del agregado, versión de esquema, versión de estado, recuperación y recuento de publicaciones pendientes
  - Registrar fallos de carga y escritura con causa, operación y ruta, sin contenido de diario, memorias ni respuestas
  - Incluir el diagnóstico en la inspección existente del bot
  - Escribir pruebas de contenido de diagnóstico, redacción y fallo de escritura
  - _Requirements: 2.5, 5.5_

- [x] 4. Hacer consistentes las operaciones de varios conjuntos de datos
- [x] 4.1 Archivar la temporada antes de reiniciarla
  - Crear una instantánea completa y validable de la temporada actual
  - Guardar metadatos de temporada, fecha y referencia dentro del archivo
  - Abortar el reinicio si el archivo no se puede crear o validar
  - Escribir pruebas de archivo correcto, archivo inválido y fallo previo al reinicio
  - _Requirements: 7.1, 7.2, 3.1, 3.3_

- [x] 4.2 Aplicar retención de temporadas y copias
  - Conservar un número configurable de temporadas archivadas y copias de migración
  - No eliminar el estado activo, su copia de recuperación, la migración pendiente ni publicaciones pendientes
  - Continuar y registrar errores si una eliminación individual falla
  - Hacer la limpieza idempotente y respetuosa con los límites configurados
  - Escribir pruebas de conservación, eliminación, artefactos protegidos y segunda ejecución
  - _Requirements: 7.2, 7.3, 7.4_

- [x] 4.3 Reiniciar la temporada como una única operación persistente
  - Validar la autorización antes de archivar o mutar
  - Archivar primero y después mutar temporada, pareja, afinidad, usuarios, citas, memorias, diario e historiales dentro de una transacción
  - Conservar los registros de turno para no reprocesar mensajes antiguos
  - Anunciar la nueva temporada solo después del commit
  - Restaurar el estado en memoria y no anunciar éxito si falla la persistencia
  - Escribir pruebas de reinicio completo, fallo de escritura, anuncio tardío y conservación del registro de turnos
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4.4 Auditar y reconducir todos los puntos de mutación directa
  - Revisar registro de usuarios, afinidad, memorias, diario, historiales, citas y coronación
  - Eliminar escrituras directas a archivos de estado
  - Hacer que cada mutación simple solicite una persistencia y cada mutación compuesta use una transacción
  - Cubrir con pruebas las rutas de recuerdos, regalos, cierre de cita, confesión y reinicio de conversación
  - _Requirements: 3.1, 3.5, 5.1_

- [x] 5. Implementar el registro durable y el orden de turnos
- [x] 5.1 Registrar y deduplicar turnos de forma durable
  - Reclamar todos los identificadores de mensajes de un lote antes de llamar al modelo
  - Rechazar duplicados mediante el índice durable, también después de reiniciar
  - Marcar committed con el texto exacto que se publicará
  - Marcar published después de que Discord acepte el envío
  - Marcar failed ante errores de generación, validación o abandono
  - Podar registros antiguos sin eliminar los pendientes de publicación
  - Escribir pruebas de reclamación, duplicado, transiciones, abandono y poda
  - _Requirements: 4.2, 4.3, 4.4_

- [x] 5.2 Procesar turnos en orden FIFO por canal
  - Aceptar lotes en el orden de recepción del canal
  - Ejecutar un solo trabajo por canal y permitir avance independiente entre canales
  - Liberar la cola cuando un trabajo falla para no bloquear el siguiente
  - Escribir pruebas de orden, concurrencia entre canales, fallo aislado y cierre de cola
  - _Requirements: 4.1, 4.5, 5.3_

- [x] 5.3 Separar la generación de la aplicación del turno
  - Hacer que la generación solo lea estado y no registre usuarios, afinidad, memorias, diario, historiales ni transiciones de cita
  - Mover el registro de usuarios, afinidad, memorias, diario, historial y cita al paso síncrono de aplicación
  - Descargar el GIF durante la generación y conservarlo para la publicación posterior
  - Separar los avisos inmediatos de búsqueda de los avisos que afirman una persistencia
  - Mantener las instantáneas y la traza del estado previo al turno
  - Escribir pruebas que detecten cualquier mutación durante la generación
  - _Requirements: 3.4, 4.4, 5.2, 5.3_

- [x] 5.4 Orquestar reclamación, generación, validación, commit y publicación
  - Reclamar el lote y persistir el estado processing antes de generar
  - Generar sin bloqueo global y validar el borrador antes de aplicarlo
  - Aplicar mutaciones y marcar committed en una sola transacción persistente
  - Publicar solo después del commit y marcar published después del envío
  - Devolver avisos y texto de confesión para publicarlos después del commit
  - Escribir pruebas del flujo completo, duplicate, stale, fallo de commit y fallo de publicación
  - _Requirements: 4.2, 4.3, 4.4, 3.4, 3.5, 5.1_

- [x] 5.5 Gestionar turnos obsoletos sin mutaciones parciales
  - Rechazar la aplicación si cambió la cita o la temporada durante la generación
  - Marcar el turno como failed con el motivo y no duplicar historial ni afinidad
  - Enviar un aviso honesto pidiendo repetir la interacción
  - Escribir pruebas de cita reemplazada, cita cerrada, temporada cambiada y aviso al usuario
  - _Requirements: 5.2, 5.5, 3.5_

- [x] 6. Recuperar publicaciones y cerrar la fiabilidad operativa
- [x] 6.1 Reanudar respuestas confirmadas pero no publicadas
  - Al arrancar, distinguir turnos committed de published y failed
  - Republicar solo los committed dentro de la vigencia configurada
  - Publicar en el canal original, con texto plano como contenido recuperable
  - Marcar published después de la aceptación de Discord y conservar el pendiente si falla
  - Escribir pruebas de reanudación, canal no disponible, fallo de envío y expiración
  - _Requirements: 4.3, 4.4, 3.4_

- [x] 6.2 Abandonar procesos interrumpidos y aplicar vigencia de publicación
  - Convertir registros processing antiguos en failed al arrancar
  - No reprocesar automáticamente un mensaje interrumpido
  - Expirar committed fuera de la vigencia sin publicar contenido obsoleto
  - Escribir pruebas de reinicio con processing, committed reciente y committed expirado
  - _Requirements: 4.2, 4.4, 5.5_

- [x] 6.3 Integrar el diagnóstico y la recuperación en el arranque real
  - Ejecutar abandono de procesamientos y reanudación de publicaciones al estar listo el bot
  - Informar de recuperación, bloqueo, cuarentena y pendientes sin exponer datos privados
  - Liberar recursos y bloqueos en apagados normales y fallos de arranque
  - Escribir una prueba de arranque completo con estado migrado, recuperado y publicaciones pendientes
  - _Requirements: 1.4, 2.5, 4.4, 6.5_

- [x] 6.4 Verificar la fiabilidad de extremo a extremo
  - Simular caída antes del commit, entre commit y publicación, y durante el reinicio de temporada
  - Verificar que el estado anterior o el nuevo son válidos, nunca una mezcla
  - Verificar que un mismo mensaje no se procesa dos veces tras reiniciar
  - Verificar que la cola conserva orden y que canales distintos no se bloquean entre sí
  - Ejecutar la suite completa y la regresión de transcripciones
  - Probar un arranque real sobre una copia del directorio de datos actual
  - _Requirements: 3.3, 4.1, 4.4, 5.1, 5.2, 5.3, 6.5, 7.4_
