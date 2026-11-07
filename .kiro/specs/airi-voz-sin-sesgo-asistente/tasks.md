# Plan de implementación

- [x] 1. Definir pruebas que expresen la voz conversacional autónoma de Airi
- [x] 1.1 Cubrir ausencia de cortesía y complacencia automáticas
  - Añadir expectativas para que el prompt permita respuestas neutrales, directas y discrepantes sin obligación de validar, agradecer o tranquilizar.
  - Verificar que el trato a personas nuevas no presuponga cercanía efusiva.
  - Comprobar que el prompt completo y el compacto transmitan las mismas reglas.
  - Mantener las pruebas enfocadas en texto ensamblado y no en frases rígidas de respuesta generada por el modelo.
  - _Requirements: 1.1, 1.2, 1.3, 2.2, 3.1, 3.5_

- [x] 1.2 Cubrir calidez contextual e invariantes del contrato
  - Comprobar que la guía permita calidez cuando vínculo o contexto la justifiquen.
  - Comprobar que las instrucciones por afinidad no impongan cordialidad o calidez universales.
  - Verificar que ejemplos de ambos contratos no sugieran aprobación como respuesta predeterminada.
  - Verificar que campos, valores permitidos y estructura JSON permanezcan sin cambios.
  - _Requirements: 2.1, 2.3, 3.2, 3.3, 3.4, 3.5_

- [x] 2. Ajustar las instrucciones de voz para quitar el rol de asistente servicial
- [x] 2.1 Hacer contextual el tono base, el vínculo y el ánimo
  - Reemplazar directivas de cercanía/cordialidad predeterminadas por una pauta neutral cuyo tono dependa de personalidad, vínculo y situación.
  - Explicitar que Airi no necesita complacer, validar, agradecer, tranquilizar ni ofrecer ayuda por reflejo.
  - Conservar respeto básico y la posibilidad de mostrar calidez, apoyo o afecto genuinos cuando encajen.
  - Mantener la posibilidad de rechazar o esquivar favores no deseados y de disentir sin hostilidad.
  - Aclarar que `warmth` describe el estado emocional del turno y no una obligación de trato social.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

- [x] 2.2 Alinear instrucciones y ejemplos de salida
  - Actualizar ejemplos de salida completa y compacta para que no modelen aprobación o calidez automática.
  - Mantener idénticos los campos, tipos, enums y restricciones del contrato JSON.
  - Inspeccionar el prompt final de ambas modalidades para confirmar que no reaparezca una instrucción contradictoria.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Validar la integración y preservar el comportamiento no relacionado
- [x] 3.1 Ejecutar regresiones focalizadas de prompts
  - Ejecutar primero las pruebas nuevas y confirmar que detectan el comportamiento anterior antes de aplicar el cambio.
  - Ejecutar las pruebas unitarias de naturalidad y variantes de prompt después del cambio.
  - Revisar el diff para confirmar que no cambien afinidad, relación, lógica de salida ni modificaciones locales preexistentes ajenas a esta feature.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
