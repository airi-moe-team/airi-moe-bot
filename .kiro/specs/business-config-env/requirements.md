# Requisitos: configuración de negocio por entorno

## Introducción

Airi ya permite ajustar muchos límites y tiempos mediante variables de entorno, pero algunas decisiones de negocio —como los niveles de afinidad, las escenas de cita y los rasgos base— permanecen fijadas en el código. Esta mejora permite personalizar esos valores en `.env` y desplegarlos desde `.env.example`, conservando el comportamiento actual cuando no se configuran.

## Requisitos

### Requisito 1: Configurar las opciones de negocio que hoy son estáticas
**Objetivo:** Como responsable de Airi, quiero ajustar las opciones de negocio mediante variables de entorno para cambiar su comportamiento sin editar el código.

#### Criterios de aceptación
1. WHEN Airi inicia con `AFFINITY_LEVELS` definido THEN Airi SHALL usar los umbrales y nombres configurados para mostrar los niveles de afinidad y determinar la elegibilidad asociada a esos niveles.
2. WHEN Airi inicia con `DATE_SCENES` definido THEN Airi SHALL usar la lista configurada como escenas disponibles o de reserva para las citas.
3. WHEN Airi inicia con `SELF_TRAITS_ALLOWLIST` y `SELF_BASE_TRAITS` definidos THEN Airi SHALL usar los rasgos permitidos y sus valores base configurados al crear y validar el modelo editable de identidad.
4. IF cualquiera de esas variables no está definida THEN Airi SHALL conservar para esa opción el comportamiento predeterminado actual.
5. IF una variable contiene datos inválidos o incompatibles THEN Airi SHALL ignorar el valor inválido, usar el predeterminado de esa opción y emitir una advertencia sin impedir el inicio del bot.
6. WHEN Airi aplica niveles o rasgos configurados THEN Airi SHALL conservar las reglas de integridad: umbrales ordenados, nombres no vacíos y únicos, y correspondencia entre los rasgos permitidos y sus valores base.

### Requisito 2: Hacer efectivos los límites de cambios de identidad
**Objetivo:** Como responsable de Airi, quiero que los límites documentados para los cambios de identidad controlen realmente su frecuencia.

#### Criterios de aceptación
1. WHEN `SELF_KEY_DAILY_LIMIT` está definido THEN Airi SHALL permitir como máximo esa cantidad de cambios de la misma clave durante la ventana `SELF_KEY_DAILY_SECONDS`.
2. IF `SELF_KEY_DAILY_LIMIT` no está definido THEN Airi SHALL mantener el límite actual de un cambio por clave y ventana.
3. WHILE se aplica el límite por clave THEN Airi SHALL seguir respetando también `SELF_UPDATE_MIN_INTERVAL`.

### Requisito 3: Documentar y mantener coherente la configuración
**Objetivo:** Como persona que instala o mantiene Airi, quiero encontrar cada opción configurable documentada en ambos archivos de entorno para conocer su formato y efecto.

#### Criterios de aceptación
1. WHEN se incorpora una variable de configuración de negocio THEN el proyecto SHALL documentar su nombre, propósito, formato y valor predeterminado en `.env` y `.env.example`.
2. WHEN se carga una variable documentada en los archivos de entorno THEN Airi SHALL consumirla efectivamente; el proyecto SHALL eliminar de esos archivos cualquier variable obsoleta o sin efecto.
3. WHEN se proporcionan colecciones o mapas en variables de entorno THEN los archivos de entorno SHALL mostrar ejemplos con un formato inequívoco y válido.
4. IF las variables nuevas no están presentes en un despliegue existente THEN Airi SHALL seguir funcionando con los valores predeterminados actuales.

### Requisito 4: Preservar las constantes estructurales
**Objetivo:** Como responsable del proyecto, quiero externalizar solo decisiones editables de negocio para mantener en código las definiciones que forman parte del contrato interno del sistema.

#### Criterios de aceptación
1. WHEN se externaliza configuración THEN el proyecto SHALL mantener en código los estados de máquina, operaciones permitidas, esquemas y demás constantes estructurales que no sean opciones de negocio.
2. WHEN se modifica una opción de negocio mediante el entorno THEN Airi SHALL aplicar el cambio sin alterar los contratos de datos persistidos ni el núcleo inmutable de identidad.
