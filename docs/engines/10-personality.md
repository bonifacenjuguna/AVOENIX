# Personality Engine (`personality`) — v0.0.0

**Status:** partial  
**Depends on:** memory, emotion

Base character plus per-user adaptation (explicit preferences, observed style, emotional situation) as an inspectable StyleProfile.

## Interface

`PersonalityEngine.observe(scope, LanguageResult)`, `profile(scope, emotion) -> StyleProfile`

## Capabilities

- five style dimensions + emoji level
- explicit preference overrides
- running observation of user style (stored in memory)
- emotion-aware moderation
- explainable reasons list

## Known limitations

- Only English surface cues are observed.
- Observed style is a crude running average, not a user model.
- No long-term personality drift or multiple selectable personas in v0.0.0.

## Error handling

Missing memory yields the base character.

## Extension mechanism

Adjust base traits and adaptation rules in `engines/personality/engine.py`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
