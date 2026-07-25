CREATE TABLE query_policy_record (
  query_policy_identity TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK(schema_version='QueryPolicy@1'),
  content_hash TEXT NOT NULL UNIQUE,
  canonical_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE source_policy_record (
  source_policy_identity TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL CHECK(schema_version='SourcePolicy@1'),
  content_hash TEXT NOT NULL UNIQUE,
  canonical_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE source_rights_profile (
  rights_profile_id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL CHECK(subject_type IN ('source','fixture_member')),
  subject_id TEXT NOT NULL,
  source_identity TEXT NOT NULL,
  terms_version TEXT NOT NULL,
  automation_allowed INTEGER NOT NULL CHECK(automation_allowed IN (0,1)),
  local_storage_allowed INTEGER NOT NULL CHECK(local_storage_allowed IN (0,1)),
  derived_use_allowed INTEGER NOT NULL CHECK(derived_use_allowed IN (0,1)),
  repository_redistribution_allowed INTEGER NOT NULL CHECK(repository_redistribution_allowed IN (0,1)),
  packaged_distribution_allowed INTEGER NOT NULL CHECK(packaged_distribution_allowed IN (0,1)),
  reviewed_on TEXT NOT NULL,
  evidence_sha256 TEXT REFERENCES object_blob(sha256),
  UNIQUE(subject_type,subject_id,terms_version)
);

INSERT INTO query_policy_record
SELECT
  query_policy_version,
  'QueryPolicy@1',
  canonical_sha256(
    '{"migration_basis":"pre0013_identity_commitment","preserved_identity":"'
    || query_policy_version || '","schema_version":"QueryPolicy@1"}'
  ),
  '{"migration_basis":"pre0013_identity_commitment","preserved_identity":"'
    || query_policy_version || '","schema_version":"QueryPolicy@1"}',
  min(last_success_at)
FROM data_snapshot
GROUP BY query_policy_version;

INSERT INTO source_policy_record
SELECT
  source_policy_version,
  'SourcePolicy@1',
  canonical_sha256(
    '{"migration_basis":"pre0013_identity_commitment","preserved_identity":"'
    || source_policy_version || '","schema_version":"SourcePolicy@1"}'
  ),
  '{"migration_basis":"pre0013_identity_commitment","preserved_identity":"'
    || source_policy_version || '","schema_version":"SourcePolicy@1"}',
  min(last_success_at)
FROM data_snapshot
GROUP BY source_policy_version;

INSERT INTO source_rights_profile
SELECT
  'rights_' || substr(canonical_sha256(
    fixture_member_id || ':' || source_identity || ':' || terms_version
    || ':' || deterministic_replay_allowed || ':'
    || local_storage_allowed || ':0:'
    || repository_redistribution_allowed || ':'
    || packaged_distribution_allowed || ':' || reviewed_on
    || ':' || coalesce(raw_sha256,'')
  ),1,24),
  'fixture_member',
  fixture_member_id,
  source_identity,
  terms_version,
  deterministic_replay_allowed,
  local_storage_allowed,
  0,
  repository_redistribution_allowed,
  packaged_distribution_allowed,
  reviewed_on,
  CASE
    WHEN raw_sha256 IN (SELECT sha256 FROM object_blob) THEN raw_sha256
    ELSE NULL
  END
FROM fixture_rights_profile;

ALTER TABLE provider_attempt RENAME TO provider_attempt_0012;

CREATE TABLE provider_attempt (
  attempt_id TEXT PRIMARY KEY,
  invocation_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  dataset TEXT NOT NULL,
  source_identity TEXT NOT NULL,
  source_authority TEXT NOT NULL,
  real_source_url TEXT NOT NULL,
  redacted_params_json TEXT NOT NULL,
  response_headers_json TEXT NOT NULL,
  source_time_precision TEXT NOT NULL,
  terms_profile TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('complete','partial','missing','failed','rate_limited','empty','complete_with_substitution')),
  cache_disposition TEXT NOT NULL,
  raw_sha256 TEXT REFERENCES object_blob(sha256),
  retrieved_at TEXT NOT NULL,
  error_code TEXT,
  cursor_before TEXT,
  cursor_after TEXT,
  cursor_disposition TEXT NOT NULL,
  query_policy_identity TEXT NOT NULL REFERENCES query_policy_record(query_policy_identity),
  source_policy_identity TEXT NOT NULL REFERENCES source_policy_record(source_policy_identity),
  rights_profile_id TEXT NOT NULL REFERENCES source_rights_profile(rights_profile_id)
);

INSERT INTO provider_attempt
SELECT
  p.*,
  (
    SELECT min(s.query_policy_version)
    FROM normalized_version v
    JOIN data_snapshot_member m
      ON m.normalized_version_id=v.normalized_version_id
    JOIN data_snapshot s ON s.data_snapshot_id=m.data_snapshot_id
    WHERE v.source_attempt_id=p.attempt_id
  ),
  (
    SELECT min(s.source_policy_version)
    FROM normalized_version v
    JOIN data_snapshot_member m
      ON m.normalized_version_id=v.normalized_version_id
    JOIN data_snapshot s ON s.data_snapshot_id=m.data_snapshot_id
    WHERE v.source_attempt_id=p.attempt_id
  ),
  COALESCE(
    (
      SELECT rights_profile_id
      FROM source_rights_profile r
      WHERE r.subject_type='fixture_member'
        AND r.source_identity=p.source_identity
        AND r.subject_id=p.provider_id || ':' || p.dataset
      LIMIT 1
    ),
    NULL
  )
FROM provider_attempt_0012 p;

DROP TABLE provider_attempt_0012;
DROP TABLE fixture_rights_profile;

ALTER TABLE data_snapshot RENAME TO data_snapshot_0012;

CREATE TABLE data_snapshot (
  data_snapshot_id TEXT PRIMARY KEY,
  scope_id TEXT NOT NULL,
  snapshot_purpose TEXT NOT NULL CHECK(snapshot_purpose IN ('research','workflow','market','chart')),
  requested_date TEXT NOT NULL,
  effective_session_date TEXT NOT NULL,
  as_of_at TEXT NOT NULL,
  market_timezone TEXT NOT NULL,
  calendar_version TEXT NOT NULL,
  query_policy_identity TEXT NOT NULL REFERENCES query_policy_record(query_policy_identity),
  source_policy_identity TEXT NOT NULL REFERENCES source_policy_record(source_policy_identity),
  freshness_policy_version TEXT NOT NULL,
  membership_hash TEXT NOT NULL,
  freshness_status TEXT NOT NULL CHECK(freshness_status IN ('valid','stale','missing')),
  quality_status TEXT NOT NULL CHECK(quality_status IN ('pass','warning','blocking')),
  coverage_expected INTEGER NOT NULL,
  coverage_eligible INTEGER NOT NULL,
  coverage_excluded INTEGER NOT NULL,
  coverage_missing INTEGER NOT NULL,
  stale_by_days INTEGER NOT NULL,
  freshness_basis TEXT NOT NULL,
  last_success_at TEXT NOT NULL,
  UNIQUE(snapshot_purpose,as_of_at,membership_hash,query_policy_identity,source_policy_identity,freshness_policy_version)
);

INSERT INTO data_snapshot
SELECT
  data_snapshot_id,
  scope_id,
  snapshot_purpose,
  requested_date,
  effective_session_date,
  as_of_at,
  market_timezone,
  calendar_version,
  query_policy_version,
  source_policy_version,
  freshness_policy_version,
  membership_hash,
  freshness_status,
  quality_status,
  coverage_expected,
  coverage_eligible,
  coverage_excluded,
  coverage_missing,
  stale_by_days,
  freshness_basis,
  last_success_at
FROM data_snapshot_0012;

DROP TABLE data_snapshot_0012;

CREATE TABLE official_filing_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version,
  security_id TEXT NOT NULL REFERENCES security,
  issuer_identity TEXT NOT NULL,
  authority TEXT NOT NULL,
  document_identity TEXT NOT NULL,
  accession_or_document_id TEXT NOT NULL,
  filing_type TEXT NOT NULL,
  report_period_end TEXT,
  document_object_sha256 TEXT NOT NULL REFERENCES object_blob,
  content_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK(byte_size>=0),
  correction_status TEXT NOT NULL CHECK(correction_status IN ('original','amended','corrected','superseded')),
  filing_identity_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE financial_fact_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version,
  filing_normalized_version_id TEXT NOT NULL REFERENCES official_filing_version,
  taxonomy TEXT NOT NULL,
  concept TEXT NOT NULL,
  context_identity TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  instant TEXT,
  unit TEXT NOT NULL,
  currency TEXT,
  scale INTEGER NOT NULL,
  value_decimal TEXT NOT NULL,
  statement_scope TEXT NOT NULL,
  source_fact_identity TEXT NOT NULL,
  fact_identity_hash TEXT NOT NULL UNIQUE,
  CHECK(
    (instant IS NOT NULL AND period_start IS NULL AND period_end IS NULL)
    OR
    (instant IS NULL AND period_end IS NOT NULL)
  )
);

CREATE TRIGGER query_policy_record_no_update
BEFORE UPDATE ON query_policy_record
BEGIN SELECT RAISE(ABORT,'QUERY_POLICY_IMMUTABLE'); END;

CREATE TRIGGER query_policy_record_no_delete
BEFORE DELETE ON query_policy_record
BEGIN SELECT RAISE(ABORT,'QUERY_POLICY_IMMUTABLE'); END;

CREATE TRIGGER source_policy_record_no_update
BEFORE UPDATE ON source_policy_record
BEGIN SELECT RAISE(ABORT,'SOURCE_POLICY_IMMUTABLE'); END;

CREATE TRIGGER source_policy_record_no_delete
BEFORE DELETE ON source_policy_record
BEGIN SELECT RAISE(ABORT,'SOURCE_POLICY_IMMUTABLE'); END;

CREATE TRIGGER source_rights_profile_no_update
BEFORE UPDATE ON source_rights_profile
BEGIN SELECT RAISE(ABORT,'SOURCE_RIGHTS_IMMUTABLE'); END;

CREATE TRIGGER source_rights_profile_no_delete
BEFORE DELETE ON source_rights_profile
BEGIN SELECT RAISE(ABORT,'SOURCE_RIGHTS_IMMUTABLE'); END;

CREATE TRIGGER provider_attempt_policy_identity_no_update
BEFORE UPDATE OF query_policy_identity,source_policy_identity,rights_profile_id
ON provider_attempt
BEGIN SELECT RAISE(ABORT,'PROVIDER_ATTEMPT_POLICY_IMMUTABLE'); END;

CREATE TRIGGER provider_attempt_no_delete
BEFORE DELETE ON provider_attempt
BEGIN SELECT RAISE(ABORT,'PROVIDER_ATTEMPT_IMMUTABLE'); END;

CREATE TRIGGER data_snapshot_policy_identity_no_update
BEFORE UPDATE OF query_policy_identity,source_policy_identity
ON data_snapshot
BEGIN SELECT RAISE(ABORT,'DATA_SNAPSHOT_POLICY_IMMUTABLE'); END;

CREATE TRIGGER data_snapshot_no_delete
BEFORE DELETE ON data_snapshot
BEGIN SELECT RAISE(ABORT,'DATA_SNAPSHOT_IMMUTABLE'); END;

CREATE TRIGGER official_filing_no_update
BEFORE UPDATE ON official_filing_version
BEGIN SELECT RAISE(ABORT,'OFFICIAL_FILING_IMMUTABLE'); END;

CREATE TRIGGER official_filing_no_delete
BEFORE DELETE ON official_filing_version
BEGIN SELECT RAISE(ABORT,'OFFICIAL_FILING_IMMUTABLE'); END;

CREATE TRIGGER financial_fact_no_update
BEFORE UPDATE ON financial_fact_version
BEGIN SELECT RAISE(ABORT,'FINANCIAL_FACT_IMMUTABLE'); END;

CREATE TRIGGER financial_fact_no_delete
BEFORE DELETE ON financial_fact_version
BEGIN SELECT RAISE(ABORT,'FINANCIAL_FACT_IMMUTABLE'); END;
