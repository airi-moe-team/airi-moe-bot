# Plan de implementación

- [x] 1. Externalizar niveles de afinidad y escenas de cita
- [x] 1.1 Añadir parseo validado de niveles de afinidad desde el entorno
  - Escribir primero pruebas para JSON válido, valor ausente, JSON mal formado, umbrales desordenados, nombres vacíos o duplicados y menos de siete niveles.
  - Asegurar que los valores válidos conservan el orden y los tipos esperados por el dominio.
  - Asegurar que valores ausentes o inválidos conservan los niveles actuales y generan una advertencia sin revelar el contenido de la variable.
  - _Requirements: 1.1, 1.4, 1.5, 1.6, 3.4_

- [x] 1.2 Aplicar los niveles configurados a la afinidad y elegibilidad de citas
  - Escribir pruebas que comprueben etiquetas y umbrales personalizados.
  - Hacer que la elegibilidad de citas dependa del umbral del séptimo nivel y no del nombre visible del nivel.
  - Verificar que los niveles predeterminados mantienen el comportamiento existente.
  - _Requirements: 1.1, 1.4, 4.1, 4.2_

- [x] 1.3 Añadir parseo validado de escenas de cita desde el entorno
  - Escribir primero pruebas para lista JSON válida, variable ausente, JSON inválido, lista vacía y elementos vacíos.
  - Aplicar la lista configurada a las escenas mostradas y a la selección de reserva.
  - Conservar las escenas actuales como fallback y verificar que las rutas de selección nunca reciben una lista vacía.
  - _Requirements: 1.2, 1.4, 1.5, 3.3, 3.4_

- [x] 2. Externalizar los rasgos editables y activar su límite diario
- [x] 2.1 Cargar y validar juntos la allowlist y los valores base de rasgos
  - Escribir primero pruebas para listas/mapas JSON válidos y para variables ausentes, inválidas o definidas de forma incompatible.
  - Verificar unicidad de nombres, coincidencia exacta entre allowlist y mapa base, y valores dentro del rango permitido.
  - Aplicar los valores configurados al sembrado, normalización y guardarraíles de actualización de identidad.
  - Asegurar que una configuración inválida restaura el conjunto predeterminado completo y emite advertencia.
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 4.1, 4.2_

- [x] 2.2 Hacer efectivo el máximo de cambios por clave durante la ventana
  - Escribir primero pruebas para límite predeterminado de uno, límite configurado de dos, límite alcanzado, ventana vencida e intervalo global mínimo.
  - Contar cambios de la misma clave dentro de la ventana configurada y bloquear al alcanzar el máximo.
  - Mantener el comportamiento actual cuando el límite falta o es inválido.
  - _Requirements: 2.1, 2.2, 2.3, 3.2_

- [x] 3. Cargar y documentar la configuración de entorno correctamente
- [x] 3.1 Cargar dotenv antes de importar módulos que leen configuración
  - Crear un bootstrap central de dotenv y probar su carga antes de importar constantes de dominio.
  - Importar el bootstrap primero desde el entrypoint del bot, el CLI directo de trazas y el replay directo.
  - Mantener lazy en `__main__` los imports de los handlers de trazas y reproducción.
  - Probar en procesos aislados que los tres entrypoints ven los valores del entorno al inicializar constantes.
  - _Requirements: 1.1, 1.2, 1.3, 3.4_

- [x] 3.2 Documentar las variables JSON en ambos archivos de entorno
  - Añadir `AFFINITY_LEVELS`, `DATE_SCENES`, `SELF_TRAITS_ALLOWLIST` y `SELF_BASE_TRAITS` con ejemplos JSON válidos, propósito y defaults actuales.
  - Mantener las claves de `.env` y `.env.example` sincronizadas, preservando los valores locales existentes y cualquier secreto.
  - Explicar que los rasgos deben configurarse como conjunto y que retirar rasgos puede eliminarlos al normalizar el estado.
  - Confirmar que `SELF_KEY_DAILY_LIMIT` se mantiene documentada porque ya tendrá un consumidor efectivo.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 4. Verificar integración y compatibilidad de extremo a extremo
- [x] 4.1 Probar la configuración del proceso con valores personalizados y fallbacks
  - Usar procesos aislados para verificar carga temprana y aplicación de valores personalizados en `airi`, `airi-trace` y `airi-replay`.
  - Verificar que las variables ausentes o inválidas conservan los defaults y no impiden el arranque.
  - Confirmar que la forma de los datos persistidos y el núcleo inmutable de identidad no cambian.
  - _Requirements: 1.4, 1.5, 3.4, 4.1, 4.2_

- [x] 4.2 Ejecutar la suite de regresión y cerrar la cobertura de requisitos
  - Ejecutar las pruebas unitarias, de integración y la suite completa existente.
  - Corregir regresiones relacionadas con afinidad, citas, identidad o importación de comandos.
  - Comprobar que cada requisito tiene una prueba o verificación correspondiente y que no queda configuración documentada sin efecto.
  - _Requirements: 1.1–1.6, 2.1–2.3, 3.1–3.4, 4.1–4.2_
