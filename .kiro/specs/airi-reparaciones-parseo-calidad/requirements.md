# Requirements Document

## Introduction

Airi genera sus respuestas como JSON estricto y el harness aplica hasta cinco reparaciones independientes (truncation, empty_reply, repeat_reply, question_close, disconnect) cuando la salida no es usable o incumple calidad. Ese flujo es costoso en el peor caso (hasta 5 llamadas extra al modelo local), difícil de mantener (cinco bloques `try/except` duplicados) y no cubre la coherencia del hilo en canales con varios usuarios. Esta feature fusiona las cinco reparaciones en dos políticas (`parse_repair` y `quality_repair`) con un verificador semántico `conversation_review`, añade parches deterministas sin LLM y extiende la telemetría para conservar el diagnóstico fino.

## Requirements

### Requirement 1: Fusión de las reparaciones en dos políticas
**Objective:** As a maintainer, I want the five ad-hoc repairs collapsed into two policies, so that the worst-case latency and maintenance cost drop.

#### Acceptance Criteria
1. WHEN the primary output has no usable reply (empty after parse, unparseable JSON, or `finish_reason == "length"`) THEN the ConversationService SHALL issue exactly one `parse_repair` call with a symptom-specific hint.
2. WHEN the primary output parses but fails a quality check THEN the ConversationService SHALL issue exactly one `quality_repair` call combining all detected issues into a single hint.
3. WHEN both a parse failure and a quality failure would apply THEN the ConversationService SHALL run `parse_repair` first and re-evaluate quality on its result before deciding.
4. WHEN a repair call produces no usable reply THEN the ConversationService SHALL keep the previous usable output or fall back to the deterministic patch, never silence the turn.
5. The ConversationService SHALL never issue more than 2 repair calls (`parse_repair` + `quality_repair`) in a single turn.
6. `parse_repair` SHALL reuse the original turn `messages` including Airi's persona prompt; only `conversation_review` SHALL run without persona.

### Requirement 2: Reparación en modo revisión del borrador
**Objective:** As a maintainer, I want `quality_repair` to revise the draft instead of regenerating blind, so that fixes are surgical and preserve Airi's voice.

#### Acceptance Criteria
1. WHEN `quality_repair` runs THEN the ConversationService SHALL send the draft as an `assistant` message followed by a `user` message listing the detected issues with literal evidence.
2. WHEN the repair produces an empty reply or a reply shorter than 50% of the draft THEN the ConversationService SHALL discard it and apply the deterministic patch.
3. WHEN the repair prompt is built THEN it SHALL instruct the model not to mention the correction, not to apologize, and to return only the corrected JSON.
4. WHEN the revision is received THEN it SHALL be accepted only if it shares at least 60 % of the draft's normalized tokens (excluding the flagged spans); otherwise it SHALL be discarded and the deterministic patch applied.

### Requirement 3: Parches deterministas sin LLM
**Objective:** As a user, I want cheap, deterministic safety nets before any LLM repair, so that tokens are spent only when needed.

#### Acceptance Criteria
1. WHEN the reply contains ChatML or template artifacts (`<|im_end|>`, `<|im_start|>`, `</s>`, `### Human:`, `### Assistant:`, leading `User:`/`Assistant:`) THEN `clean_reply` SHALL strip them.
2. WHEN the reply states Airi is leaving but `disconnect.leave` is false THEN the pipeline SHALL strip the leaving claim from the text (never silently keep a false departure).
3. WHEN the reply contains out-of-character phrases ("como modelo de lenguaje", "como una ia", "como asistente virtual") THEN `is_out_of_character` SHALL flag it as a quality issue.
4. The deterministic patches SHALL run before any repair decision and again after a successful repair.
5. WHEN `strip_leaving_claims` removes a claim THEN it SHALL cut at sentence boundaries and validate the residue (at least 20 characters, initial capital, terminal punctuation); if invalid it SHALL keep the original text and raise the issue for `quality_repair`.
6. WHEN both the strip and `quality_repair` fail THEN the pipeline SHALL publish the original text with `leave=false` and mark the turn as `repair_exhausted`.

### Requirement 4: Verificador semántico `conversation_review`
**Objective:** As a user, I want Airi's replies checked against the conversation thread, so that she does not answer off-topic, to the wrong person, or nonsense.

#### Acceptance Criteria
1. WHEN a turn produces a usable reply THEN the ConversationService SHALL issue a `conversation_review` call with the last 8-10 history entries (with author labels) plus the draft.
2. WHEN the review returns issues THEN each issue SHALL include `kind`, an `impact` enum (`breaks_thread`, `wrong_person`, `incoherent`, `self_reset`) and a literal `evidence` quote from the draft; issues without evidence SHALL be discarded and free-text prose fields SHALL NOT be accepted.
3. WHEN the review call fails, times out, or returns invalid JSON THEN the ConversationService SHALL publish the cleaned draft (fail-open).
4. WHEN the review prompt is built THEN it SHALL instruct the model to approve by default and only flag when the draft clearly does not connect to any recent message, addresses someone who did not speak, or resets Airi's identity.
5. The `conversation_review` call SHALL use a short prompt (no full system prompt) with `low` reasoning budget.
6. The `conversation_review` SHALL run under a judge role stripped of Airi's persona; `quality_repair` SHALL keep the persona prompt so the revision stays in character.

### Requirement 5: Activación en todos los turnos
**Objective:** As a maintainer, I want the review available in both multi-user and 1-a-1 turns, so that coherence is checked wherever the thread matters.

#### Acceptance Criteria
1. The `conversation_review` SHALL run in every turn that produces a usable reply, regardless of channel mix.
2. WHEN a turn is a quick turn or a date turn THEN the ConversationService SHALL skip the review.
3. The review SHALL be gated by a config flag (`AIRI_CONVERSATION_REVIEW`, default on) so it can be disabled without code changes.

### Requirement 6: Detección de repetición de usuarios
**Objective:** As a user, I want Airi not to echo what a human said, so that replies feel original.

#### Acceptance Criteria
1. WHEN `reply_repeats_history` is evaluated THEN it SHALL also consider messages with `role == "user"`, with a minimum prefix of 60 normalized characters.
2. WHEN Airi's reply copies the opening of a user's recent message THEN it SHALL be treated as a quality issue.

### Requirement 7: Telemetría y trazas
**Objective:** As an operator, I want fine-grained repair diagnostics without 5 purpose names, so that benchmarks stay comparable.

#### Acceptance Criteria
1. WHEN a repair call is made THEN its `purpose` SHALL be `parse_repair` or `quality_repair`.
2. WHEN a repair call is made THEN it SHALL record a `repair_reason` (`truncation`, `empty`, `invalid_json`, `repeat`, `repeat_user`, `ooc`, `disconnect`, `off_topic`, `wrong_addressee`, `nonsense`, `self_reset`); combined quality issues SHALL be joined deterministically.
3. WHEN a `conversation_review` call is made THEN its `purpose` SHALL be `conversation_review`.
4. The `TurnEvent` SHALL expose `review_on_topic`, `review_issues` and `review_ms` fields.
5. All new purposes SHALL be documented in `.kiro/specs/observabilidad-ttft-llama-server/design.md`.
6. WHEN a turn exhausts its repair budget and the deterministic patch is the last word THEN the `TurnEvent` SHALL record `repair_exhausted=true`.

### Requirement 8: Presupuesto y fail-open
**Objective:** As a maintainer, I want a hard cap on LLM calls per turn, so that latency stays bounded.

#### Acceptance Criteria
1. A single turn SHALL issue at most: 1 primary + 1 parse_repair + 1 conversation_review + 1 quality_repair.
2. WHEN the review fails THEN the turn SHALL still publish the cleaned draft.
3. WHEN the total repair path exceeds the cap THEN the deterministic patch SHALL be the last word.

### Requirement 9: Fuera de alcance
**Objective:** As a maintainer, I want explicit non-goals, so that the scope stays bounded.

#### Acceptance Criteria
1. This feature SHALL NOT add network retries or backoff to `http_llm.py`.
2. This feature SHALL NOT add in-character fallback messages when the server is down.
3. This feature SHALL NOT verify memory/RAG hallucinations (grounded check remains web-only).
4. This feature SHALL NOT add deterministic topic-term checks coupled to `domain/web.py`.

### Requirement 10: Retroalimentación de ejecución offline (con humano en medio)
**Objective:** As a maintainer, I want failed turns to become auditable evidence for harness improvements, so that the system evolves through review instead of automatic mutation.

#### Acceptance Criteria
1. WHEN a turn exhausts its repair budget THEN the trace SHALL keep the full execution record with its `repair_reason` and `repair_exhausted` flag.
2. The observability CLI SHALL expose a `repairs` subcommand that groups exhausted and repaired turns by `repair_reason` and lists their `correlation_id`.
3. The system SHALL NOT mutate harness prompts or deterministic rules automatically from telemetry.
4. Any proposed harness change derived from this feedback SHALL be applied through the existing human-gated SDD feedback flow.
