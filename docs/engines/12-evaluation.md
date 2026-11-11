# Evaluation & Confidence Engine (`evaluation`) — v0.0.1

**Status:** partial  
**Depends on:** language, reasoning

Per-turn evidence-support assessment and a dataset runner with per-category metrics, failure reports and a calibration table.

## Interface

`EvaluationEngine.assess_turn(...)`, `run_suite(cases, respond, ...)`, `latest_runs()`

## Capabilities

- turn assessment with explicit not_evaluated stages
- weighted-geometric combination of stage scores
- dataset execution with expectation checks (status, task, text, memory)
- accuracy per metric, category and split (dev / hold-out)
- expected-calibration-error style table of stated confidence vs correctness
- persistence of runs (evaluation_runs)

## Known limitations

- Measures only what the supplied dataset covers; a high score on a small dataset is not a general claim.
- Confidence bands are fixed thresholds, not calibrated; the calibration table reports how far off they are.
- The bundled dataset is small and authored by the AVOENIX developers (not independent).

## Error handling

A crashing case counts as FAILED, never skipped.

## Extension mechanism

Add check types in `EvaluationEngine.check`; datasets are plain JSON.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
