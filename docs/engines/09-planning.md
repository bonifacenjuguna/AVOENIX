# Planning / Goal Engine (`planning`) — v0.0.1

**Status:** partial  
**Depends on:** memory

Goal tracking, rule-based decomposition, dependency DAG, critical-path scheduling, progress, plan evaluation.

## Interface

`PlanningEngine.detect_goal / create_goal / add_task / update_task / rank / next_actions / evaluate`

## Capabilities

- goal detection from first-person statements
- decomposition by sequencing cues
- cycle / unknown-dependency detection
- critical path, slack, makespan vs total effort
- priority x urgency ranking
- next-action selection
- plan evaluation findings

## Known limitations

- Decomposition is clause-splitting, not domain planning: AVOENIX does not know how to plan a trip, it structures what the user says.
- Single-resource assumptions; no calendars, working hours or resource levelling.
- Goals live in memory rows (no dedicated table in schema 0001).

## Error handling

Cyclic dependencies and infeasible schedules are reported as structured problems.

## Extension mechanism

Decomposition patterns live in `decompose()`; scheduling functions are pure and replaceable.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
