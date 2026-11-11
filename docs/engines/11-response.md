# Response Generation Engine (`response`) — v0.0.1

**Status:** partial  
**Depends on:** personality, emotion, reasoning

Compositional English realisation with style adaptation, greeting grammar, emoji intelligence and repetition awareness.

## Interface

`ResponseGenerationEngine.generate(plan, style, emotion, state, seed, name, occasion) -> Response`

## Capabilities

- answers for entities/values/numbers/booleans/lists with faithful restatement of the asked proposition
- support (premise) clauses and step explanations driven by style
- honest unknown / underdetermined / contradiction / unsupported renderings
- greetings, farewells, thanks and social replies composed from slots
- emoji decisions with explicit reasons
- repetition tracking across skeletons, emoji and whole texts
- verified-learning acknowledgements (never claims unverified learning)

## Known limitations

- English only. Alternatives are authored skeleton options; the variety is combinatorial but finite and not learned.
- No paraphrase generation beyond the authored skeletons; unusual relations fall back to a generic rendering.
- Style adaptation is limited to the five profile dimensions plus emoji.
- Long multi-paragraph discourse planning is not implemented.

## Error handling

Realisation failures fall back to a plain statement of the facts; variation never changes facts.

## Extension mechanism

Add message realisers `_m_<type>` and weighted `Opt` skeletons; emoji rules in `engines/response/emoji.py`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
