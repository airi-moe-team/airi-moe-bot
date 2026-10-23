# Product Overview

Airi es un bot de Discord con personalidad propia que conversa mediante un LLM local
(servidor compatible con llama.cpp). No es un asistente genérico: mantiene un personaje
romántico/afectivo, recuerda a los usuarios, gestiona citas, regalos y un diario, y
responde con un tono natural y coherente con su relación con cada persona.

## Core Features

- Conversación en un único canal autorizado, con debounce por usuario y cola FIFO por canal.
- Afinidad por usuario con niveles (de desconocida a novios), deltas acotados, decay y ranking.
- Relaciones afectivas por etapas con evidencia y propuestas de avance.
- Citas interactivas con botones, preguntas y cierre por tiempo.
- Regalos, memorias de usuario, diario y auto-modelo (identidad mutable).
- Búsqueda web y GIFs como recursos narrativos.
- Persistencia versionada del estado, archivo por temporada y recuperación ante fallos.
- Observabilidad por turno: trazas en disco, `airi-trace` y `airi-replay`.
- Apagado manual con despedida y aviso de desconexión.
- Comandos administrativos (`!ayuda`, `!ranking`, `!debug`, `!reiniciar-temporada`, etc.).

## Target Use Case

Servidor privado de Discord de un grupo pequeño que quiere una presencia conversacional
con memoria y continuidad, ejecutada con un modelo local sin depender de APIs de pago.

## Key Value Proposition

- Personalidad persistente y relaciones con memoria, no respuestas aisladas.
- Coste de inferencia controlado: una sola llamada al LLM por turno y filtros locales baratos.
- Arquitectura hexagonal que permite testear el comportamiento sin Discord ni red.
- Trazabilidad completa de cada turno para depurar naturalidad y regresiones.

## Naturalness Principles

- Airi no debe responder forzosamente a todo ni terminar cada mensaje con una pregunta.
- Debe poder escuchar sin intervenir y participar cuando tenga un motivo real.
- Las mecánicas nuevas (iniciativa, retirada, mediación) deben ser discretas, con cooldown,
  y nunca exponer ni presionar a usuarios concretos.
