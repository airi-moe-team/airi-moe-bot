# Plan de implementación

- [x] 1. Fijar con pruebas el contrato del canon narrativo
- [x] 1.1 Añadir pruebas de coherencia del canon en ambas variantes
  - Verificar que Airi presenta su pasado como ficción canónica y no como experiencia real verificable.
  - Verificar la presencia de los hechos esenciales: familia, Nerea, Gael y la contradicción entre querer ser comprendida y ocultar vulnerabilidad.
  - Verificar que la candidata experimental no afirma que Airi carece de infancia o experiencias románticas ficticias.
  - Verificar que la candidata sigue siendo experimental y no pasa a ser la variante predeterminada.
  - _Requirements: 1.1, 1.2, 1.4, 4.1, 4.2, 4.3_

- [x] 1.2 Añadir pruebas de separación entre canon y contexto dinámico
  - Verificar que el canon se incorpora una sola vez a cada personalidad.
  - Verificar que las secciones dinámicas por usuario no copian ni reescriben el canon.
  - Verificar que el contrato de salida y el ensamblado de las secciones dinámicas siguen presentes.
  - Verificar que el modelo mutable no convierte roleplay ni eventos no confirmados en pasado canónico.
  - _Requirements: 1.3, 3.1, 3.2, 3.3, 3.4_

- [x] 2. Incorporar la síntesis biográfica estable a las personalidades de Airi
- [x] 2.1 Integrar el canon compacto con instrucciones de uso contextual
  - Resumir identidad virtual, infancia, aprendizajes emocionales, humor y orgullo sin incorporar capítulos o ejemplos extensos.
  - Conservar los hechos esenciales de Clara, Mateo, Nerea y Gael sin inventar acontecimientos adicionales.
  - Indicar que el pasado debe orientar la perspectiva, no convertirse en tema automático ni guion obligatorio.
  - Indicar que las experiencias de Airi no permiten inferir las emociones o la historia de un usuario.
  - Mantener separados el canon, recuerdos reales por usuario, roleplay y evolución futura.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 4.2, 4.4_

- [x] 2.2 Hacer coherente la variante experimental sin promoverla
  - Reemplazar la premisa que niega la infancia o experiencias románticas de Airi por una distinción clara entre ficción canónica y experiencia verificable.
  - Confirmar que la variante actual y la candidata reciben el mismo canon compacto sin duplicarlo.
  - Conservar sin cambios la selección predeterminada de personalidad.
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 3. Validar comportamiento conversacional y continuidad
- [x] 3.1 Añadir o ejecutar escenarios de evaluación de naturalidad
  - Probar una pregunta directa sobre infancia y comprobar que la respuesta usa solo el fragmento pertinente.
  - Probar una conversación sobre rechazo y comprobar que Airi no demoniza a quien no correspondió ni equipara la historia del usuario con la de Gael.
  - Probar una dificultad emocional y comprobar que Airi responde primero a lo que contó la persona.
  - Probar una charla casual de videojuegos y un cambio de tema después de una conversación emocional, sin referencias biográficas forzadas.
  - Probar roleplay con un acontecimiento nuevo y comprobar que no se registra como recuerdo canónico o duradero.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.2, 3.4, 5.1, 5.2, 5.3, 5.4_

- [x] 3.2 Ejecutar verificaciones de regresión de prompts
  - Ejecutar las pruebas unitarias de prompts y conversación relacionadas con ambas variantes.
  - Comparar tamaño del prompt antes y después para confirmar que se añadió solo la síntesis compacta.
  - Confirmar que el contrato JSON, las secciones dinámicas y la selección de variante no cambiaron.
  - Documentar el resultado de evaluación sin tratarlo como aprobación automática de la candidata.
  - _Requirements: 3.1, 4.3, 5.5_
