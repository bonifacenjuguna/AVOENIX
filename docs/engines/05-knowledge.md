# Knowledge Engine (`knowledge`) — v0.0.0

**Status:** implemented  
**Depends on:** storage

Typed fact store with provenance, scoping, contradiction handling, fuzzy entity lookup and lexical retrieval.

## Interface

`KnowledgeEngine.seed / assert_fact / assert_proposition / query / search / retract / restore / list_facts`

## Capabilities

- facts over typed terms (entities, kinds, concepts, quantities)
- three-level visibility (global/project/user)
- provenance and reliability ranking
- duplicate, negation, functional and ordering-cycle contradiction detection
- supersession with history
- fuzzy entity lookup
- BM25 lexical retrieval over statements
- runtime self-model
- curated seed knowledge (small, labelled unverified)

## Known limitations

- World knowledge is tiny (≈90 curated facts); anything else must come from users or administrators.
- Contradiction detection covers direct negation, functional predicates and order cycles — not arbitrary logical inconsistency.
- No ontology alignment or entity linking beyond normalised-label matching and fuzzy suggestion.

## Error handling

Writing seed-level sources at user level raises `ScopeError`; unknown terms return suggestions instead of guesses.

## Extension mechanism

Add curated facts to `engines/knowledge/seed.py` (idempotent, deterministic ids); new predicates need a realiser entry in the Response Engine.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
