# Context Engine (`context`) — v0.0.0

**Status:** implemented  
**Depends on:** language

Tracks conversational state and resolves pronouns, demonstratives, ordinals and elliptical follow-ups.

## Interface

`ContextEngine.resolve(doc, state) -> ResolutionReport`, `update(state, doc, user_text=..., system_text=...)`, `new_state(cid)`

## Capabilities

- entity salience with recency decay
- pronoun resolution (agreement, selectional, binding, salience)
- ambiguity detection instead of forced guesses
- options list with ordinal/previous/next/'that one' references
- topic tracking
- unresolved-question tracking
- elliptical follow-up completion
- serialisable state

## Known limitations

- Resolution is intra- and inter-utterance only for singular/plural pronouns and simple demonstratives; split antecedents, bridging ('the engine' of a car) and event anaphora are not resolved.
- Ellipsis completion substitutes one entity in the previous question; it states its interpretation so users can correct it.

## Error handling

Ambiguous references produce a clarification request rather than a guess.

## Extension mechanism

Resolution rules are ordered functions in `engines/context/engine.py`; state is serialisable.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
