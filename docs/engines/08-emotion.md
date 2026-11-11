# Emotion / Sentiment Engine (`emotion`) — v0.0.1

**Status:** partial  
**Depends on:** language

Lexicon + rule affect analysis: valence, arousal, emotion categories, negation, intensity, emoji and punctuation cues.

## Interface

`EmotionEngine.analyze(LanguageResult) -> EmotionSignal`

## Capabilities

- valence/arousal estimation
- negation scope and intensifiers
- emoji and punctuation cues
- contrast clauses ('but')
- mixed-affect detection
- explicit certainty = amount of cue evidence

## Known limitations

- A ~200-word authored lexicon: unusual wording, slang, irony and sarcasm are not understood.
- No speaker modelling: it reports expressed affect in this message only.
- Not validated against a labelled corpus in v0.0.1 (see evaluation docs).

## Error handling

Never raises on text content; neutral with `certainty=0` when no cues exist.

## Extension mechanism

Extend the lexicon in `engines/emotion/engine.py`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
