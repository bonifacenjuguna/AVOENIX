-- Rollback of revision 0002. Removes the Knowledge Integrity columns/tables. Original 0001 data is untouched; claims' provenance,
-- verification, assessments, conflicts and revision history are LOST. Back up first. Rows with source_type 'imported' are re-labelled
-- 'derived' so the 0001 CHECK constraint can be restored.
DROP TABLE IF EXISTS knowledge_revisions;
DROP TABLE IF EXISTS knowledge_conflicts;
DROP INDEX IF EXISTS knowledge_verification_idx;
UPDATE knowledge_facts SET source_type = 'derived' WHERE source_type = 'imported';
ALTER TABLE knowledge_facts DROP CONSTRAINT IF EXISTS knowledge_facts_source_type_check;
ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_source_type_check
    CHECK (source_type IN ('user_statement', 'external_verified', 'seed_curated', 'derived', 'learned', 'system'));
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS memory_id;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS assessment;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS verification;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS claim_type;
ALTER TABLE knowledge_facts DROP COLUMN IF EXISTS provenance;
INSERT INTO schema_info (key, value) VALUES ('schema_revision', '0001')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
