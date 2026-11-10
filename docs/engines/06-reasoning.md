# Reasoning Engine (`reasoning`) — v0.0.0

**Status:** partial  
**Depends on:** knowledge, language

Pluggable strategies over ACR: relational ordering (+CSP cross-check), taxonomy/syllogism, containment, attribute lookup, exact arithmetic, contradiction detection, induction, hypothesis generation.

## Interface

`ReasoningEngine.reason(scope, LanguageResult, conversation_id) -> ReasoningResult`

## Capabilities

- transitive ordering with equality classes, negated comparisons, superlatives and numeric measurements
- backtracking CSP enumeration used to cross-check and to score hypotheses
- is-a / property inheritance syllogisms and located_in chains
- exact rational arithmetic
- contradiction detection (negation, single-valued attributes, ordering cycles)
- Laplace-based inductive generalisation (tentative)
- unknown / underdetermined reporting with the missing information
- runtime registration of additional strategies

## Known limitations

- Coverage is limited to the predicates the English front-end can produce; unsupported constructions yield 'unsupported', not guesses.
- No temporal reasoning, no numeric word problems with state, no probabilistic inference.
- Abduction is limited to ordering hypotheses; there is no general rule-based abductive engine.
- Confidence values are evidence-support scores, not calibrated probabilities.

## Error handling

A failing strategy is recorded in `strategies_tried` and does not abort other strategies.

## Extension mechanism

`ReasoningEngine.register(Strategy, first=False)` / `unregister(name)` at runtime; each strategy declares `applies(query)` and `run(query, factbase)`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
