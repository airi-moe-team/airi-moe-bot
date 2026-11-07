# Requirements Document

## Project Description (Input)

Mostrar el indicador de escritura de Discord durante la generación `peer_reply` de Airi o Luna, sin confundirlo con una decisión de participación ni publicarlo tras concluir el turno. Habilitar la captura opt-in de las respuestas LLM de los trabajos peer para diagnosticar fallos de parseo: `peer_reply` actualmente no pasa `call_context`, y el directorio de artefactos configurado (`./private-llm-artifacts`) es relativo a `/app`, no persistente ni escribible por el usuario del contenedor. Mantener privacidad, control de turnos, reparaciones existentes y pruebas automatizadas.

## Introduction

En la ronda de prueba, Luna recibió un trabajo de respuesta entre bots y su modelo trabajó durante minutos, pero Discord no mostró «escribiendo…». La variable de captura LLM cargada tras reiniciar tampoco permite investigar ese trabajo: la llamada coordinada no proporciona contexto de traza y la ruta configurada no es persistente ni escribible dentro del contenedor. Se necesita una señal de actividad mientras se genera la respuesta y un registro opt-in, privado y persistente de las salidas para distinguir los fallos de formato.

## Requirements

### Requirement 1: Actividad visible durante la respuesta coordinada
**Objective:** Como usuario de Discord, quiero ver cuándo Luna o Airi está generando su respuesta, para saber que su turno no se perdió.

#### Acceptance Criteria
1. WHEN un bot inicia la generación de un trabajo de respuesta entre bots o proactivo THEN el worker SHALL activar el indicador «escribiendo…» de Discord para ese bot mientras procesa la generación y cualquier reparación de formato.
2. WHEN el trabajo termina, falla o se cancela THEN el worker SHALL detener la activación del indicador de escritura.
3. WHEN un bot evalúa solamente si participar THEN el worker SHALL NOT mostrar el indicador de escritura de respuesta.
4. WHEN la salida válida del modelo es silencio THEN el worker SHALL NOT publicar un mensaje por el solo hecho de haber mostrado el indicador.
5. WHILE un trabajo coordinado está en ejecución THE worker SHALL conservar el control de publicación del coordinador y SHALL NOT enviar contenido sin autorización.

### Requirement 2: Evidencia de las respuestas LLM coordinadas
**Objective:** Como operador, quiero poder investigar el formato de las salidas de cada llamada de respuesta, para identificar por qué falla incluso después de repararla.

#### Acceptance Criteria
1. WHEN se habilita expresamente la captura LLM THEN el worker SHALL producir artefactos de respuesta para las llamadas primaria y de reparación de un trabajo de respuesta coordinada.
2. WHEN se registran las llamadas de un mismo trabajo THEN el worker SHALL permitir distinguir la llamada primaria de la reparación sin depender del contenido generado.
3. WHEN la captura no está habilitada THEN el worker SHALL NOT escribir artefactos de payload o respuesta por ese trabajo.
4. WHEN la captura falla THEN el worker SHALL conservar el resultado funcional de la llamada LLM y SHALL señalar el fallo de captura sin incluir prompts, contenido de Discord ni respuesta cruda en logs ordinarios.
5. WHEN una respuesta entre bots falla por formato THEN el worker SHALL conservar el límite existente de una sola reparación y SHALL NOT publicar el contenido inválido.

### Requirement 3: Persistencia y privacidad de artefactos
**Objective:** Como operador, quiero que los artefactos sean recuperables tras reinicios sin exponer conversaciones o secretos accidentalmente.

#### Acceptance Criteria
1. WHEN se configura una ruta de captura dentro del contenedor THEN el despliegue SHALL usar un directorio privado que el proceso del bot pueda escribir y que sobreviva a la recreación de contenedores.
2. WHEN se almacenan artefactos de respuesta THEN el sistema SHALL mantenerlos separados por bot para evitar mezclar resultados de Airi y Luna.
3. WHEN se inspeccionan logs ordinarios THEN el sistema SHALL NOT imprimir contenido bruto de peticiones, respuestas, secretos ni conversaciones capturadas.
4. WHEN se realizan pruebas automatizadas THEN las pruebas SHALL comprobar el indicador durante el trabajo, su cierre en éxito/error, la captura activada y desactivada y la continuidad del comportamiento de silencio y publicación.
