# Informe de feedback 2: perfil estable de gustos (FB-006)

**Fecha:** 2026-10-23 20:09 UTC · **Elementos:** 1 (major) · **Objetivos:** requirements, design

## FB-006 — Perfil estable de gustos configurable en .env

**Problema:** hoy el autodescubrimiento puede cambiar `tastes.*` y el matcher usa el
modelo mutable: la evolución de Airi alteraría los disparadores sin querer.

**Decisión del usuario:** fuente canónica configurable en `.env` (única fuente para
prompt y matcher), sin listas duplicadas.

**Cambios acordados:**
- `AIRI_PROFILE` (JSON: loves/dislikes/favorite_food/favorite_flower). Si está definida y
  válida, bootstrap la aplica a `world["preferences"]` (transacción + save). Vacía o
  inválida → warning y fallback al perfil persistido o defaults.
- `self_model`: gustos/favoritos fuera de la allowlist de `self_update`; el texto de
  reglas del prompt se actualiza.
- El matcher del modo espectador lee el perfil canónico (`world["preferences"]`), no el
  modelo mutable.
- Tests: parseo/validación del perfil de env, aplicación al estado y que un self_update
  de gustos ya no aplica.

**Aprobaciones a restablecer:** requirements + design (se reaprueban tras revisión).
