# Knowledge Integrity (v0.0.1)

**Rule:** remembering that someone said something and believing it are separate operations. Every stored statement is a *claim* with provenance and a verification state. Only established knowledge answers questions as fact.

## The failure this fixes
v0.0.0: "What is the capital of the USA?" → "I don't know"; user: "The capital of the USA is New York." → "Okay, I'll remember that"; later "New York is probably the capital of the USA."
v0.0.1: the first answer is *Washington, D.C.* (curated seed), the user's statement is recorded as an **unverified, contradicted claim** (reply says so and gives the established fact), the original statement stays retrievable, and later answers stay *Washington, D.C.*, with a note that the user earlier said New York and that it was not verified.

## Claim model (`claim/1.0`, `intelligence/representation/claims.py`)
Typed, serialisable (`to_dict`/`from_dict`), schema-versioned. Fields: `id, subject, predicate, object, polarity, claim_type, provenance, source, source_ref, verification, status, assessment, statement, conversation_id, created_at, updated_at, conflicts, memory_id`.

| Dimension | Values |
|---|---|
| provenance | `user_provided`, `system_inference`, `internal_knowledge`, `independently_verified`, `imported`, `unresolved` |
| claim_type | `world` (about the world), `personal` (about the user), `premise` (scenario premise, e.g. "John is older than Peter") |
| verification | `verified`, `curated`, `supported`, `unverified`, `contradicted`, `conflicting`, `not_applicable` |
| epistemic level | `established`, `supported`, `unverified`, `conflicting`, `insufficient`, `self_reported`, `unknown` |

It adapts the existing fact store (`knowledge_facts` gained columns) rather than adding a parallel store; `ACR` is unchanged.

**"curated" is not "verified".** The 92-fact seed is developer-curated; it is established for answering, but no independent verification source exists (`verified` / `independently_verified` are reserved and unused today). The Studio and API say `curated`, never `verified`, for seed facts.

## Assessment: explainable, and split
`Assessment` = `level`, `verification`, `interpretation_confidence` (did we parse the statement?), `support` (evidence the statement is true: `None` = not assessable, `0.0` = no evidence, else noisy-or of evidence weights), `refutation`, `basis` (human-readable reasons) and `evidence` items (`supports` / `contradicts` / `context`). Interpretation confidence never counts as factual support. A source-reliability *prior* is displayed but **never counted as evidence**. Repeating a claim adds no support (a restatement counter only). Turn-level `confidence.overall` is not reported for `unverified_claim` answers; `confidence.factual_support` is exposed separately.

## Validation (`engines/knowledge/integrity.py`, offline, deterministic)
Checks run on every assertion and are returned in `AssertResult.checks`:
`source_reliability` · `contradiction` · `internal_knowledge_comparison` · `evidence_availability` · `logical_consistency`.

| Detected | How |
|---|---|
| negation | same statement, opposite polarity |
| functional | single-valued attribute with a different value (capital, name, age…); different **time qualifiers** do not conflict |
| taxonomic | is-a contradicted via the taxonomy, including inherited negation |
| location | located-in incompatible with established country-level containment |
| ordering | comparison that would make an order circular (partial order) |
| agreement/entailment | exact match with established facts; is-a and located-in chains |

**Coverage limits (honest):** world-claim classification is by predicate (`attr.capital`, `attr.currency`, `attr.president`, `attr.population`, `rel.located_in`, kind-level `rel.is_a`); other relations are treated as scenario premises. Functional predicates are a fixed list. Containment is country-level. There is no external verification, no numeric tolerance (population "about 50 million" vs an exact value is not reconciled), no temporal reasoning beyond qualifier inequality, and only claims the English parser extracts as structured propositions are validated. Hearsay ("Someone told me X") and "What about X?" directly after a statement are not parsed (see limitations).

## Conflicts and resolution
Conflicts are preserved in `knowledge_conflicts` (kind, both fact ids, status `open|resolved`, resolution `established_precedence | revised | manual_choice | dismissed`, note, details, timestamps). A user claim contradicting **established** knowledge is `contradicted` (the established fact keeps winning; both are kept). Two unestablished claims that disagree are both `conflicting`; neither is believed, neither is deleted. If established knowledge supports a claim, peer conflicts are marked `settled_by_established_knowledge` and the claim becomes `supported`. The newest claim is never assumed right.

## Revisions
`knowledge_revisions` is append-only: previous and updated snapshots, source, reason, verified flag. A user correction ("No, the capital is Marinus", "Actually I am 31") supersedes that user's earlier claim (status `superseded`, history kept) but the new claim is validated like any other.

## Memory vs knowledge
For a world statement the orchestrator writes (1) a claim and (2) a separate episodic memory "User said: …", linked by `memory_id`. "Savah told AVOENIX the capital is New York" is memory; "the capital is New York" is an unverified claim; "Washington, D.C." is curated knowledge. Personal facts about the user (`@user`) are `personal` / `not_applicable`: believed as self-reported, never presented as world fact. World claims follow the user across conversations; scenario premises do not.

## Reasoning, context, response
`FactBase.get()` = established + personal + premise facts (the knowledge basis). `FactBase.claims()` returns unestablished world claims. `AttributeLookup` answers from the basis and attaches `user_claims`; with no established answer but a claim it returns status `unverified_claim` ("I don't have an established answer… You told me X, but I couldn't verify that"). Context follow-ups ("What about Kenya?") resolve to the same lookups and therefore the same claim states.

## Evaluation
`evaluation/datasets/knowledge_integrity_v1.json`, metrics: claim classification, provenance preserved, contradiction detected, unsupported presented as fact, confidence for claims, revision history preserved. Results are in `docs/TESTING_REPORT.md`; there are no targets (none were invented). The dataset is 10 developer-written cases; **two were changed after first failing** (hearsay wording and a follow-up after a statement) because they exposed parser limits, not knowledge-integrity defects; the limits are listed, not fixed.

## Storage
Migration `0002_knowledge_integrity.sql` (see `docs/DEPLOYMENT.md`): new `knowledge_facts` columns `provenance, claim_type, verification, assessment (jsonb), memory_id`; widened `source_type` check; one-time backfill (seed/system/learned → `curated`; user statements → `user_provided`/`unverified`; `@user` facts → `personal`/`not_applicable`; `disputed` → `conflicting`); tables `knowledge_conflicts`, `knowledge_revisions`; index; `schema_info` → `0002`. Idempotent; rollback script provided. Verified on PostgreSQL 16 (apply twice, rollback, re-apply, scratch DB). **Not tested:** transaction atomicity (the test adapter is non-atomic), concurrent writers, RLS.
