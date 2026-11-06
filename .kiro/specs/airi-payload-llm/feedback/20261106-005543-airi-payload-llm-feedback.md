# Feedback — airi-payload-llm

- Elementos: 1 (major).
- Aprobaciones a reiniciar: requirements, design y tasks.
- Responsable: agente incorpora los cambios; usuario revisa y aprueba cada fase.

## FB-001 — Conservar el texto de razonamiento en el response artifact para depuración

El response sidecar actual conserva el contenido visible (`content`) pero no el razonamiento (`reasoning_content`). Se propone capturarlo como campo separado en respuestas streaming y no-streaming, solo dentro del sidecar opt-in. No se copiará a la traza ni a `final_reply`; el replay continuará usando exclusivamente `content`.

**Siguiente checkpoint:** revisar y aprobar requirements, después design y tasks. La implementación queda pendiente de esas aprobaciones.
