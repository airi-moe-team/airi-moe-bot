# Feedback: centralización semántica de GIF

- **Feature:** `experimento-prompt-thinking-latencia`
- **Ítems:** 1 (major: 1)
- **Aprobaciones a reiniciar:** requirements, design y tasks, porque los tres documentos reciben cambios.
- **Responsable:** implementación de Airi; revisión y aprobación: usuario.
- **Próximo checkpoint:** revisar los documentos actualizados antes de comenzar el código.

## FB-001 — Centralizar semántica observable de GIF y desacoplarla del ánimo

**Contexto e impacto:** Las instrucciones de GIF aparecen en más de una sección. La superposición puede hacer que el modelo lea `shy` como un estado tímido interno, no como pudor visible, y que reconsidere `wave` frente a `shy` en saludos.

**Actualización recomendada:**

- **Requirements:** establecer una única sección `REACCIONES VISUALES Y SELECCIÓN DE GIF` con intención, ánimo, reacción observable y catálogo semántico completo; cambiar la guía dinámica de ánimo; simplificar la descripción de `gif` sin retirar su lista completa de valores. Preservar API, contrato y restricciones.
- **Design:** emitir la sección semántica central desde las variantes full y compact; retirar la antigua `Guía de GIFs`; asegurar que los textos dinámicos y variantes rollback no contengan instrucciones contradictorias.
- **Tasks:** añadir pruebas primero para unicidad, IDs/significados, ánimo independiente y contrato; refactorizar; ejecutar suite y validaciones; realizar repeticiones live de los seis escenarios, capturando la petición real y reportando las métricas disponibles.

**Criterio de comparación:** solo presentar comparación antes/después como evidencia si se ejecuta con el mismo modelo, configuración y condiciones equivalentes. Las muestras de una sola respuesta no prueban causalidad ni reducción estadística del razonamiento.
