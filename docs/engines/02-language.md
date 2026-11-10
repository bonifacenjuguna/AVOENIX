# Language Understanding Engine (`language`) — v0.0.0

**Status:** implemented  
**Depends on:** input

English morphology, tagging, shallow parsing and semantic construction into ACR.

## Interface

`LanguageEngine.analyze(InputPacket) -> LanguageResult` (ACR document + confidence + diagnostics)

## Capabilities

- tokenisation incl. contractions, numbers, times, emoji
- sentence segmentation
- inflectional morphology (analysis + generation)
- rule-based POS tagging with contextual disambiguation
- NP/VP/PP/clause chunk parsing incl. passives, coordination, subordination
- negation scope on predicates
- comparatives/equatives/superlatives mapped to dimensions
- event role assignment (dative alternation, passive)
- questions: yes/no, wh-subject/object/adjunct/degree, ellipsis
- pronoun/definite/ordinal reference nodes with agreement features
- arithmetic sub-language
- typo and elongation repair
- speech acts from structure

## Known limitations

- Shallow parser: no full recursive grammar, relative clauses are only partly analysed, gapping/ellipsis beyond simple fragments is unsupported.
- Lexicon is authored and modest (~200 verbs, ~60 gradable adjectives); unknown words are guessed from morphology and may be mis-tagged.
- Quantifier scope, collective vs distributive readings and metaphor are not modelled.
- Interpretation confidence is a heuristic evidence score, not a probability.

## Error handling

Unparseable input yields a low-confidence result with diagnostics, never an exception; internal failures raise `EngineError`.

## Extension mechanism

Extend the lexicon (`engines/language/en/lexicon.py`: `GRADABLE`, `RELATIONAL_NOUNS`), gazetteer, or register ACR concepts via `representation.concepts.register`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
