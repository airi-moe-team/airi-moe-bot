# Feedback de desarrollo — airi-interaccion-natural

- **Items:** 1
- **Severidad:** 1 minor
- **Aprobaciones a reiniciar:** requirements, design y tasks.
- **Responsable:** implementación del agente; revisión final por la persona usuaria.

## FB-PREFERENCES-CATEGORIES — Separar los gustos de Airi en categorías semánticas

**Contexto e impacto:** Las trazas muestran que el modelo puede convertir un gusto amplio como “dulces” en un favorito específico como el flan, o imitar la preferencia declarada por el usuario. El perfil anterior también mezclaba actividades, curiosidad, aversiones y límites interpersonales.

**Dirección aprobada:**

- `loves`: intereses y gustos estables.
- `comforts`: cosas o actividades que reconfortan.
- `curious_about`: curiosidades; no implica que le guste o lo haya probado.
- `dislikes`: contenido o actividades que evita.
- `boundaries`: límites sobre cómo la tratan otras personas.
- `favorite_food` y `favorite_flower`: favoritos explícitos, que pueden ser categorías amplias.
- Mantener `loves` compatible con perfiles antiguos, no inferir gustos de Airi desde los del usuario y diferenciar el uso de las categorías en prompt, `!yo` y módulos consumidores.
