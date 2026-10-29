# Documento de requisitos

## Introducción

Airi debe conservar el razonamiento en todas sus llamadas al proveedor `llama`, incluidos los turnos rápidos, las reparaciones y las reflexiones estructuradas. En vez de apagarlo, los modos `low`, `medium` y `high` limitarán el presupuesto de tokens de razonamiento por petición. El presupuesto es un tope y no garantiza una calidad o cantidad exacta de razonamiento; cada nivel debe validarse con el modelo y la versión de llama.cpp instalados.

## Requisitos

### Requisito 1: Modos y política de razonamiento siempre activo
**Objetivo:** Como operador, quiero graduar el coste del razonamiento mediante presupuestos sin apagarlo, para conservar razonamiento en todas las respuestas.

#### Criterios de aceptación
1. WHEN `LLM_THINKING_MODE` no está definido o está vacío THEN la configuración SHALL seleccionar `auto`.
2. WHEN `LLM_THINKING_MODE` es `auto`, `on`, `low`, `medium` o `high` THEN la configuración SHALL normalizar y conservar el modo seleccionado.
3. WHEN `LLM_THINKING_MODE` es `off` o cualquier valor inválido THEN la configuración SHALL advertir y recurrir a `auto`.
4. WHEN el proveedor es `llama` y se realiza cualquier llamada THEN el cliente SHALL mantener reasoning activo y SHALL NOT enviar `enable_thinking=false`.
5. WHEN el modo es `auto` y el turno es rápido THEN el cliente SHALL mantener reasoning activo y SHALL aplicar el presupuesto reducido definido para el perfil rápido.
6. WHEN el modo es `on` THEN el cliente SHALL mantener reasoning activo y SHALL dejar el presupuesto sin límite por petición para que se aplique el default del servidor/template.
7. WHEN el operador consulta la documentación THEN esta SHALL indicar que los presupuestos son topes, no garantías, y que se aplican solo al proveedor `llama`.

### Requisito 2: Presupuestos por nivel
**Objetivo:** Como operador, quiero asignar un máximo de tokens de razonamiento a cada nivel, para controlar coste sin deshabilitar el razonamiento.

#### Criterios de aceptación
1. WHEN el modo global o el override por llamada es `low` THEN el cliente SHALL solicitar un presupuesto de 256 tokens de razonamiento.
2. WHEN el modo global o el override por llamada es `medium` THEN el cliente SHALL solicitar un presupuesto de 1024 tokens de razonamiento.
3. WHEN el modo global o el override por llamada es `high` THEN el cliente SHALL solicitar un presupuesto de 4096 tokens de razonamiento.
4. WHEN una llamada rápida en modo `auto` necesita presupuesto THEN el cliente SHALL solicitar el presupuesto `low` de 256 tokens y SHALL mantener reasoning activo.
5. WHEN una llamada normal en modo `auto` no especifica presupuesto THEN el cliente SHALL usar el presupuesto predeterminado del servidor/template.
6. WHEN la conversación ejecuta reparaciones o `self_service` realiza reflexión estructurada THEN la llamada SHALL solicitar `low` como override local y SHALL mantener reasoning activo.
7. WHEN el backend es llama.cpp THEN el adaptador SHALL enviar el campo de presupuesto por petición que soporte la versión instalada (propuesto: `thinking_budget_tokens`) y SHALL verificar que el presupuesto CLI no anule el override.
8. WHEN el proveedor no es `llama` THEN el adaptador SHALL omitir extensiones propietarias y SHALL conservar el comportamiento compatible con dicho proveedor.

### Requisito 3: Contrato LLM y overrides locales
**Objetivo:** Como servicio, quiero solicitar un presupuesto por llamada sin cambiar la configuración global, para aplicar límites diferentes a reparaciones y turnos rápidos.

#### Criterios de aceptación
1. WHEN un consumidor invoca `chat` o `chat_with_meta` con un nivel/override THEN el puerto SHALL propagar el presupuesto resuelto de forma consistente.
2. WHEN una petición define override de presupuesto THEN SHALL prevalecer solo para esa petición y SHALL NOT alterar llamadas siguientes.
3. WHEN se procesan respuestas con o sin streaming THEN el contrato SHALL preservar contenido y metadatos existentes.
4. WHEN se serializa cualquier petición de esta feature THEN SHALL NOT desactivar reasoning.

### Requisito 4: Metadatos y privacidad
**Objetivo:** Como operador, quiero comparar el presupuesto solicitado con el razonamiento observado, para evaluar coste y calidad por llamada.

#### Criterios de aceptación
1. WHEN se registra una llamada THEN sus metadatos SHALL incluir el presupuesto de razonamiento resuelto/enviado, junto con `reasoning_present` y `reasoning_tokens`.
2. WHEN el proveedor no admite presupuesto por petición o no se conoce el presupuesto enviado THEN el campo SHALL ser nulo y SHALL NOT inferir cumplimiento del backend.
3. WHEN se registran metadatos THEN el sistema SHALL NOT guardar prompts, historial, contenido de respuesta ni contenido de razonamiento.
4. WHEN la respuesta incluye evidencia de razonamiento THEN los metadatos existentes SHALL reflejarla independientemente del presupuesto solicitado.

### Requisito 5: Benchmark y compatibilidad
**Objetivo:** Como evaluador, quiero comparar modos y presupuestos observando tokens y calidad, sin confundir el límite solicitado con el uso real.

#### Criterios de aceptación
1. WHEN el benchmark se ejecuta con `auto`, `on`, `low`, `medium` o `high` coincidente con el cliente THEN SHALL aceptar la configuración.
2. WHEN el modo es inválido o distinto del cliente THEN el benchmark SHALL rechazar la ejecución con un error informativo.
3. WHEN presenta resultados THEN el benchmark SHALL conservar modo y presupuesto solicitado por llamada, separados de los tokens de razonamiento observados.
4. WHEN se valida el campo de presupuesto contra el backend real THEN la prueba SHALL ser no destructiva y SHALL NOT reiniciar ni reconfigurar el servidor.
5. WHEN se asignan o promueven presupuestos predeterminados THEN su calidad SHALL evaluarse en al menos cinco turnos reales antes de considerarlos validados.

### Requisito 6: Regresión de comportamiento
**Objetivo:** Como mantenedor, quiero eliminar la semántica de apagado y conservar razonamiento en todos los caminos internos.

#### Criterios de aceptación
1. WHEN se ejecutan pruebas unitarias e integración THEN SHALL verificar que `auto` rápido, llamadas primarias, reparaciones e introspecciones estructuradas no desactivan reasoning.
2. WHEN una reparación o reintento se realiza THEN SHALL usar presupuesto `low` y no una bandera de apagado.
3. WHEN se ejecuta una llamada normal en modo `auto` u `on` THEN SHALL mantener el razonamiento activo y usar el default del servidor si no se especifica presupuesto.
4. WHEN el operador consulta `.env.example` o README THEN SHALL ver la política de razonamiento siempre activo, el mapeo de niveles y la advertencia de compatibilidad del backend.
