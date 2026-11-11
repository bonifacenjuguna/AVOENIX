# Architecture (v0.0.0)

## Principles
1. **No ML.** All behaviour is explicit code: rules, graph algorithms, constraint solving, exact arithmetic, lexical retrieval.
2. **Honesty by construction.** Every conclusion carries a status (`answered / yes / no / unknown / underdetermined / contradiction / likely / unsupported …`), evidence and assumptions. Unknown is a first-class answer. Confidence is an evidence-support score, not a probability.
3. **Core independent of the web layer.** `intelligence/` imports neither FastAPI nor any third-party package.
4. **Isolation.** Every persistent read/write goes through `ScopedRepo(project_id, user_id)`.

## Turn pipeline (`intelligence/app.py: Avoenix.process_turn`)
```
text → Input → Language(ACR) → Context.resolve → Emotion → Personality.observe
     → route: Learning | Goal(Planning) | self-question | memory recall | Reasoning (+ Knowledge store)
     → Memory.record_turn → Personality.profile → build_plan → Response.generate → Evaluation.assess_turn
     → Context.update → persist (messages, turn_traces, conversation state)
```
Each stage is timed and recorded as a real `StageTrace`; a stage failure degrades the turn (`partial`) or yields a safe error reply, never a stack trace.

## ACR (`intelligence/representation`)
Typed nodes (Entity, Concept, Proposition, Intention, Logical, Quantity, Reference, Variable, …) in an `ACRDocument`; validated on build, JSON-serialisable, schema `acr/1.0` with a migration registry. The English front-end (tokenizer → morphology → tagger → chunk parser → semantic builder) is the only English-specific component; reasoning and storage see only ACR.

## Reasoning
`FactBase` merges current-turn facts with stored knowledge (respecting visibility: global / project / user). Strategies (ordering with equality classes + CSP cross-check, taxonomy, location, attribute lookup, arithmetic with `Fraction`, contradiction, induction, abduction) are registered at runtime. Ordering questions are answered only when the answer is *entailed*; otherwise the engine reports what is missing.

## Knowledge & memory
Facts have source ranking (external_verified > seed_curated > learned > user_statement > derived), statuses (active/disputed/superseded/retracted), and visibility levels. Memory has categories (working, conversational, episodic, semantic, preference, learned) with keyed supersession and ranked recall (relevance, recency, importance, reinforcement).

## Learning
classify → proposal → validation + golden regression probes → apply → **read-back verification** → `learning_records` entry; revert supported; project-wide knowledge needs admin approval. The system never claims to have learned unless the verification passed.

## Response generation
A content plan of structured messages is realised by weighted skeleton options (formality, warmth, expressiveness, conciseness, recent-use penalty) with deterministic morphology for the facts themselves, so variation never changes meaning. Emoji are optional, mirrored from the user, and never used in errors/unknowns/contradictions.

## Storage
`Backend` protocol over a whitelisted table spec: `MemoryBackend`, `PostgresBackend` (psycopg3 pool; SQL only from the spec; bound parameters). Schema `database/schemas/0001_initial.sql` + `0002_knowledge_integrity.sql` (20 tables; RLS policies present as defence in depth — **not tested** without a non-owner role).

## Service layer
`services/intelligence-api/app/core.py` (`ApiCore`) implements auth, scoping, audit, rate limiting and handlers without FastAPI; `main.py` maps HTTP onto it. The scope is derived from the session, never from request data. The Studio talks to the API only through a same-origin BFF proxy so the session cookie stays HttpOnly and the API URL stays server-side.

## Dependency graph of engines
input → language → context; language → knowledge/memory/reasoning/emotion/personality/response; learning → knowledge, memory; planning → memory; evaluation → (reads results). Exact dependencies are in `docs/engines/`.

## v0.0.1 additions
- **Claim layer** (`intelligence/representation/claims.py`, `intelligence/engines/knowledge/integrity.py`): every stored fact now carries provenance, a claim type (world / personal / premise), a verification state and a structured assessment. The Knowledge engine validates each assertion (`integrity.validate`) against established knowledge and other claims, preserves conflicts (`knowledge_conflicts`) and keeps append-only revisions (`knowledge_revisions`). See `docs/KNOWLEDGE_INTEGRITY.md`.
- **Reasoning** reads only the *knowledge basis* (established + personal + premise facts) via `FactBase.get()`; unestablished world claims are reachable only through `FactBase.claims()` and surface as the conclusion status `unverified_claim`.
- **Orchestrator** records a claim plus a separate episodic memory ("User said …") and links them (`memory_id`): memory of the utterance and belief in its content are different records.
- **API/Studio**: claim, conflict and export routes; redesigned Studio (`docs/STUDIO.md`). The 12-engine architecture is unchanged.
