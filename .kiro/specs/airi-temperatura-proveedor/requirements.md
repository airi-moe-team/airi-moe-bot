# Requirements Document

## Introducción

Airi delegará la selección de temperatura de generación al proveedor LLM. Esto evita que la configuración, el entorno o llamadas concretas del proyecto alteren la temperatura predeterminada del servidor o servicio remoto.

## Requisitos

### Requisito 1: Delegar la temperatura al proveedor
**Objetivo:** Como operador de Airi, quiero que las peticiones no establezcan temperatura, para que cada proveedor aplique su propia configuración predeterminada.

#### Criterios de aceptación
1. WHEN Airi envía una petición de chat a cualquier proveedor THEN Airi SHALL omitir el parámetro `temperature` del payload.
2. WHEN una función de Airi solicita una respuesta THEN Airi SHALL usar el mismo comportamiento sin importar el propósito de la llamada, sin temperaturas específicas por operación.

### Requisito 2: Retirar la configuración de temperatura de Airi
**Objetivo:** Como operador, quiero que temperatura no sea una opción de configuración de Airi, para evitar que una variable de entorno vuelva a controlar el muestreo.

#### Criterios de aceptación
1. WHEN se inicia Airi THEN el cliente LLM SHALL no leer ni aplicar `LLM_TEMPERATURE` ni `LLM_SKIP_TEMPERATURE`.
2. WHEN se consulta `.env.example` THEN el archivo SHALL no documentar variables para configurar u omitir temperatura.
3. WHEN se realizan cambios para retirar esta configuración THEN los valores existentes del `.env` local SHALL permanecer intactos.

### Requisito 3: Verificar la omisión del parámetro
**Objetivo:** Como mantenedor, quiero pruebas que verifiquen que las peticiones omiten temperatura, para impedir que se reintroduzca accidentalmente el control desde Airi.

#### Criterios de aceptación
1. WHEN se serializa una petición LLM THEN las pruebas automatizadas SHALL verificar que el payload no contiene la clave `temperature`.
2. WHEN se ejecuta la suite de pruebas del cliente LLM THEN las pruebas SHALL validar el comportamiento sin depender de variables de temperatura en el entorno.
