# Learning Engine (`learning`) — v0.0.0

**Status:** partial  
**Depends on:** memory, knowledge, language

Feedback -> classified proposal -> validation + regression check -> verified, reversible, audited update of preferences, facts and behaviour switches.

## Interface

`LearningEngine.learn_from_message / submit_feedback / apply / revert / approve / reject / history / run_golden`

## Capabilities

- four update classes (preference, fact correction, strategy adjustment, general knowledge)
- whitelisted, typed changes
- golden-probe regression check with automatic rejection
- read-back persistence verification
- revert with exact restoration
- full history in learning_records
- administrator approval for project-wide knowledge

## Known limitations

- Learns stored data only: no parser, strategy or model changes; nothing is trained.
- Classification is rule-based on English phrasing; unusual wording is not recognised as feedback.
- The golden regression suite is small (5 probes) and only covers knowledge answers.
- Fact corrections that conflict with curated knowledge are never applied automatically.

## Error handling

Invalid proposals raise `LearningRejected`; a failed read-back verification rolls the change back and reports failure (never claims learning).

## Extension mechanism

Add whitelisted keys to `PREFERENCE_DOMAIN` / `STRATEGY_DOMAIN` and golden probes to `GOLDEN`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
