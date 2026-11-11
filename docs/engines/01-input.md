# Input Processing Engine (`input`) — v0.0.1

**Status:** implemented  
**Depends on:** none

Validates, normalises and profiles incoming text; scopes it to supported English.

## Interface

`InputProcessingEngine.process(raw, channel, metadata) -> InputPacket`

## Capabilities

- type/size validation
- Unicode NFKC normalisation
- control/zero-width character removal
- whitespace collapsing
- elongation and shouting metadata
- function-word + script language identification
- structured packet hand-off

## Known limitations

- Language identification is coarse (script + closed-class word profiles); very short inputs default to English with low confidence.
- Only English is supported; other recognised languages are rejected with a clear error.

## Error handling

Empty/oversized/non-text input raises `InputError`; unsupported language raises `UnsupportedLanguageError` (the orchestrator turns both into a user-readable reply).

## Extension mechanism

Add function words to the language-detection profiles in `engines/input/engine.py`; new languages require a new Language Engine adapter (not provided).

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
