# Memory Engine (`memory`) — v0.0.1

**Status:** implemented  
**Depends on:** storage

Scoped, categorised memory with keyed preferences, BM25+recency+importance retrieval, expiry and inspection.

## Interface

`MemoryEngine.remember / recall / recent / set_preference / get_preference / forget / prune / inspect`

## Capabilities

- six memory categories
- keyed supersession for preferences
- bounded working memory with TTL
- BM25 + recency + importance ranking with explainable score parts
- update / forget / inspect / prune
- per-user and per-project isolation enforced in the storage layer

## Known limitations

- Retrieval is lexical: paraphrases that share no content words are not found.
- No automatic summarisation or consolidation of old memories.
- Importance is assigned by callers/heuristics, not learned.

## Error handling

Scope violations raise `ScopeError`; missing rows `NotFoundError`; storage failures `StorageError`.

## Extension mechanism

Add a memory category and its retention rule in `engines/memory/engine.py`; swap the storage `Backend`.

## Tests

See `tests/` (unit, integration, acceptance) and `docs/TESTING.md`. Health: `GET /v1/diagnostics` runs this engine's `self_check()`.
