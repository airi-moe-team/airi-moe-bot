# Requirements Document

## Introduction

Airi guarda actualmente sus datos de mundo, afinidad, citas, diario, memorias y usuarios en archivos JSON separados. Esta feature trasladará selectivamente a `develop` garantías de persistencia y fiabilidad de `feat/reingeniering-airi`, adaptándolas al modelo actual de Airi. El objetivo es que una interrupción, un JSON dañado o dos eventos cercanos no provoquen pérdida silenciosa de historia, estado parcialmente aplicado o turnos duplicados.

La feature no implica fusionar la rama completa. Se limita a proteger el estado y los turnos que ya existen en `develop`; no añade personalidad/identidad, romance, privacidad avanzada, objetivos ni iniciativas autónomas.

## Requirements

### Requirement 1: Escritura segura del estado persistente

**Objective:** Como operador de Airi, quiero que los cambios de estado se conserven sin destruir el último estado válido si una escritura se interrumpe, para que un fallo de proceso o de disco no corrompa la historia del bot.

#### Acceptance Criteria

1. WHEN Airi persista datos de mundo, afinidad, citas, diario, memorias o usuarios THEN el sistema SHALL preservar el archivo válido anterior hasta que el nuevo estado esté completo y confirmado.
2. WHEN el sistema confirme una escritura THEN el sistema SHALL haber validado la estructura y los tipos requeridos para ese conjunto de datos.
3. IF una escritura falla THEN el sistema SHALL informar del fallo al runtime y SHALL mantener disponible el último estado confirmado.
4. WHEN Airi inicie por primera vez y un archivo de datos no exista THEN el sistema SHALL distinguir ese caso de un archivo existente pero ilegible, y SHALL inicializarlo sin ocultar errores de corrupción.
5. WHEN el estado en memoria difiera del último estado confirmado THEN el sistema SHALL poder identificar que la mutación aún no está persistida y SHALL NOT presentarla como durable.

### Requirement 2: Detección y recuperación de corrupción

**Objective:** Como operador, quiero recuperar el último estado íntegro o recibir un error claro, para evitar que Airi arranque con datos vacíos y sobrescriba silenciosamente la información dañada.

#### Acceptance Criteria

1. WHEN un archivo persistido esté mal formado o no cumpla el esquema THEN el sistema SHALL conservarlo para diagnóstico y SHALL NOT tratarlo como un estado vacío válido.
2. IF existe una copia de recuperación válida THEN el sistema SHALL permitir restaurar el estado desde ella e informar que hubo recuperación.
3. IF el archivo activo y sus copias disponibles son inválidos THEN el sistema SHALL impedir que ese estado se use o sobrescriba como si fuera nuevo, y SHALL informar qué intervención necesita el operador.
4. WHEN se aparte un archivo corrupto THEN el sistema SHALL conservar una referencia identificable al original en una ubicación de cuarentena o equivalente.
5. WHEN el sistema reporte un fallo de carga o recuperación THEN el sistema SHALL incluir suficiente información operativa para distinguir archivo ausente, corrupción, incompatibilidad de esquema y fallo de I/O.

### Requirement 3: Consistencia de operaciones que cambian varios datos

**Objective:** Como usuario, quiero que acciones como reiniciar una temporada no dejen a Airi en una combinación incoherente de datos, para que su continuidad narrativa concuerde con el estado guardado.

#### Acceptance Criteria

1. WHEN una operación lógica modifique varios conjuntos de datos THEN el sistema SHALL definir un único resultado confirmado o una estrategia de recuperación que evite exponer una combinación parcial como completa.
2. WHEN se reinicie la temporada THEN el sistema SHALL persistir de forma recuperable el nuevo número de temporada y todos los cambios asociados que ya formen parte de la semántica vigente del comando.
3. IF una operación compuesta se interrumpe antes de confirmarse THEN el sistema SHALL poder determinar al reiniciar si debe completarla, revertirla o requerir intervención, sin repetir sus efectos de forma accidental.
4. WHEN Airi publique una respuesta o aviso que dependa de una mutación persistente THEN el sistema SHALL confirmar esa mutación antes de anunciarla como realizada.
5. WHEN una escritura falle durante una operación compuesta THEN el sistema SHALL comunicar el fallo y SHALL NOT informar éxito al usuario.

### Requirement 4: Orden e idempotencia de turnos

**Objective:** Como participante de una conversación, quiero que mis mensajes se procesen en orden y no se apliquen dos veces tras un reinicio, para evitar respuestas duplicadas o una historia desordenada.

#### Acceptance Criteria

1. WHEN se acepten varios mensajes de un mismo canal THEN el sistema SHALL procesar sus turnos en el orden de aceptación definido por el runtime.
2. WHEN un mensaje ya tenga un turno confirmado THEN el sistema SHALL reconocerlo por un identificador estable y SHALL NOT volver a aplicar sus mutaciones ni añadirlo otra vez al historial tras un reinicio.
3. WHEN un turno se confirme THEN el sistema SHALL conservar suficiente registro para distinguir entre turno no procesado, procesado y respuesta pendiente de publicar o ya publicada.
4. IF el proceso se interrumpe durante la generación antes de confirmar el turno THEN el sistema SHALL dejar el mensaje en un estado recuperable y SHALL NOT duplicar mutaciones confirmadas.
5. WHEN mensajes de canales independientes estén disponibles simultáneamente THEN el sistema SHALL evitar que la protección de un turno mantenga bloqueado el estado compartido durante toda una llamada lenta al modelo, siempre que la consistencia se pueda preservar.

### Requirement 5: Concurrencia de escrituras

**Objective:** Como operador, quiero que comandos y turnos concurrentes no se sobrescriban entre sí, para preservar cambios confirmados y evitar carreras en el estado compartido.

#### Acceptance Criteria

1. WHEN dos operaciones intenten modificar el mismo estado persistente THEN el sistema SHALL serializarlas o detectar el conflicto antes de confirmar una versión obsoleta.
2. WHEN una operación lea un estado para tomar una decisión y otra operación lo cambie antes del commit THEN el sistema SHALL revalidar las condiciones relevantes o rechazar el commit incompatible.
3. WHILE una llamada al modelo esté en curso THE sistema SHALL proteger las mutaciones compartidas sin mantener innecesariamente un bloqueo global durante toda la espera de red.
4. IF el runtime detecta que otra instancia ya está escribiendo los mismos datos THEN el sistema SHALL impedir la escritura concurrente o fallar de forma explícita antes de corromper el estado.
5. WHEN se detecte un conflicto de escritura THEN el sistema SHALL dejar una señal diagnóstica y SHALL NOT descartar silenciosamente cambios confirmados.

### Requirement 6: Migración y conservación de datos existentes

**Objective:** Como operador, quiero actualizar el formato de persistencia sin perder los archivos JSON que ya usa Airi, para poder adoptar las garantías nuevas de forma verificable y reversible.

#### Acceptance Criteria

1. WHEN el sistema inicie una migración que pueda cambiar el formato persistente THEN el sistema SHALL crear una copia verificable de todos los archivos de origen afectados antes de modificarlos.
2. WHEN una migración convierta datos THEN el sistema SHALL validar el destino antes de activarlo y SHALL conservar intacto el origen hasta confirmar el destino.
3. WHEN la migración se repita sobre el mismo origen THEN el sistema SHALL reconocer el resultado previo y SHALL NOT duplicar ni transformar nuevamente los datos.
4. IF un registro de origen no se puede convertir con certeza THEN el sistema SHALL conservarlo fuera del estado activo y SHALL informar la ambigüedad, en vez de asignarle valores o relaciones arbitrarias.
5. WHEN finalice una migración THEN el sistema SHALL permitir verificar que los registros esperados se conservaron y que el estado nuevo puede volver a cargarse.

### Requirement 7: Archivo, retención y trazabilidad

**Objective:** Como operador, quiero que la recuperación y el archivo no crezcan indefinidamente ni borren datos aún necesarios, para equilibrar trazabilidad y uso de almacenamiento.

#### Acceptance Criteria

1. WHEN se archiven datos de una temporada THEN el sistema SHALL distinguirlos del estado activo y SHALL evitar que el archivado se presente como un borrado irreversible.
2. WHEN se aplique una política de retención THEN el sistema SHALL conservar los artefactos necesarios para recuperación y migraciones pendientes.
3. WHEN la retención elimine copias antiguas THEN el sistema SHALL respetar límites configurados o documentados y SHALL informar de errores de eliminación.
4. IF una operación de retención se interrumpe THEN el estado activo y las copias necesarias para su recuperación SHALL permanecer utilizables.

### Restricciones y exclusiones

- El alcance se limita al estado y las funciones ya existentes en `develop`; no se exige aislamiento por servidor si eso implica introducir toda la arquitectura multiguild de la rama de origen.
- No se portan las iniciativas autónomas ni su reconciliación con Discord, porque `develop` no tiene ese ciclo de dominio.
- No se portan cambios de personalidad, identidad, romance u otras áreas funcionales de la rama.
- El diseño y la implementación deben preservar los cambios locales preexistentes y añadir pruebas de regresión antes de sustituir el comportamiento actual.
