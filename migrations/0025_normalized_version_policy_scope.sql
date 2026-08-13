-- 0025: policy-scoped normalized-version identity.
--
-- normalized_version_id already commits to (record, content, source policy),
-- but the table constraint forced (record, content) to be globally unique.
-- After a source-policy rotation, re-fetching byte-identical content could
-- neither be reused (policy-scoped dedupe misses) nor re-inserted (global
-- uniqueness violation), which blocked every subsequent sync. Rebuild the
-- table so uniqueness matches the domain identity, and denormalize the
-- creating attempt's source-policy identity onto the version row.
CREATE TABLE normalized_version_rebuild (
  normalized_version_id TEXT PRIMARY KEY,
  normalized_record_id TEXT NOT NULL REFERENCES normalized_record(normalized_record_id),
  revision_no INTEGER NOT NULL CHECK(revision_no > 0),
  content_hash TEXT NOT NULL,
  source_attempt_id TEXT NOT NULL REFERENCES provider_attempt(attempt_id),
  source_policy_identity TEXT NOT NULL,
  event_at TEXT,
  published_at TEXT,
  published_precision TEXT,
  available_at TEXT NOT NULL,
  availability_basis TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  quality_status TEXT NOT NULL CHECK(quality_status IN ('pass','warning','quarantine','blocking')),
  supersedes_version_id TEXT REFERENCES normalized_version(normalized_version_id),
  UNIQUE(normalized_record_id,revision_no),
  UNIQUE(normalized_record_id,content_hash,source_policy_identity)
);
INSERT INTO normalized_version_rebuild
SELECT v.normalized_version_id,v.normalized_record_id,v.revision_no,v.content_hash,
       v.source_attempt_id,a.source_policy_identity,
       v.event_at,v.published_at,v.published_precision,v.available_at,
       v.availability_basis,v.retrieved_at,v.quality_status,v.supersedes_version_id
FROM normalized_version v
JOIN provider_attempt a ON a.attempt_id=v.source_attempt_id;
DROP TABLE normalized_version;
ALTER TABLE normalized_version_rebuild RENAME TO normalized_version;
-- The A-share market-scope identity is CN_A_SHARE; correct stale
-- exchange-scope rows persisted before the scope rename so proven-complete
-- session selection can resolve them. Immutability triggers are lifted for
-- the corrective rewrite and restored verbatim afterwards (precedent: 0016).
DROP TRIGGER market_universe_version_no_update;
DROP TRIGGER data_snapshot_universe_ref_no_update;
UPDATE market_universe_version SET market_scope_id='CN_A_SHARE' WHERE market_scope_id IN ('SSE','SZSE','BSE');
UPDATE data_snapshot_universe_ref SET market_scope_id='CN_A_SHARE' WHERE market_scope_id IN ('SSE','SZSE','BSE');
CREATE TRIGGER market_universe_version_no_update BEFORE UPDATE ON market_universe_version BEGIN SELECT RAISE(ABORT,'MARKET_UNIVERSE_IMMUTABLE'); END;
CREATE TRIGGER data_snapshot_universe_ref_no_update BEFORE UPDATE ON data_snapshot_universe_ref BEGIN SELECT RAISE(ABORT,'DATA_SNAPSHOT_UNIVERSE_IMMUTABLE'); END;
