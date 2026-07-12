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
  status TEXT NOT NULL CHECK(status IN ('complete','partial','missing','failed','rate_limited')),
  cache_disposition TEXT NOT NULL,
  raw_sha256 TEXT REFERENCES object_blob(sha256),
  retrieved_at TEXT NOT NULL,
  error_code TEXT
  ,cursor_before TEXT
  ,cursor_after TEXT
  ,cursor_disposition TEXT NOT NULL
);
CREATE TABLE sync_cursor (
  provider_id TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  dataset TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  cursor_schema_version TEXT NOT NULL,
  cursor_value TEXT NOT NULL,
  advanced_at TEXT NOT NULL,
  PRIMARY KEY(provider_id,adapter_version,dataset,scope_id,cursor_schema_version)
);
CREATE TABLE normalized_record (
  normalized_record_id TEXT PRIMARY KEY,
  dataset TEXT NOT NULL,
  natural_key TEXT NOT NULL,
  UNIQUE(dataset,natural_key)
);
CREATE TABLE normalized_version (
  normalized_version_id TEXT PRIMARY KEY,
  normalized_record_id TEXT NOT NULL REFERENCES normalized_record(normalized_record_id),
  revision_no INTEGER NOT NULL CHECK(revision_no > 0),
  content_hash TEXT NOT NULL,
  source_attempt_id TEXT NOT NULL REFERENCES provider_attempt(attempt_id),
  event_at TEXT,
  published_at TEXT,
  published_precision TEXT,
  available_at TEXT NOT NULL,
  availability_basis TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  quality_status TEXT NOT NULL CHECK(quality_status IN ('pass','warning','quarantine','blocking')),
  supersedes_version_id TEXT REFERENCES normalized_version(normalized_version_id),
  UNIQUE(normalized_record_id,revision_no),
  UNIQUE(normalized_record_id,content_hash)
);
CREATE TABLE ohlcv_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version(normalized_version_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  session_date TEXT NOT NULL,
  market_timezone TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL CHECK(adjustment_mode='none'),
  open_decimal TEXT NOT NULL,
  high_decimal TEXT NOT NULL,
  low_decimal TEXT NOT NULL,
  close_decimal TEXT NOT NULL,
  volume_decimal TEXT NOT NULL,
  volume_unit TEXT NOT NULL,
  amount_decimal TEXT,
  amount_unit TEXT,
  currency TEXT NOT NULL
);
CREATE TABLE market_session_version (
  market_session_version_id TEXT PRIMARY KEY,
  market TEXT NOT NULL,
  session_date TEXT NOT NULL,
  is_open INTEGER NOT NULL CHECK(is_open IN (0,1)),
  calendar_version TEXT NOT NULL,
  available_at TEXT NOT NULL,
  source_attempt_id TEXT NOT NULL REFERENCES provider_attempt(attempt_id),
  UNIQUE(market,session_date,calendar_version)
);
CREATE TABLE market_universe_version (
  market_universe_version_id TEXT PRIMARY KEY,
  market_scope_id TEXT NOT NULL,
  as_of_at TEXT NOT NULL,
  source_policy_version TEXT NOT NULL,
  membership_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE market_universe_member (
  market_universe_version_id TEXT NOT NULL REFERENCES market_universe_version(market_universe_version_id),
  security_id TEXT NOT NULL,
  listed_from TEXT NOT NULL,
  delisted_after TEXT,
  st_from TEXT,
  st_to TEXT,
  source_ref TEXT NOT NULL,
  PRIMARY KEY(market_universe_version_id,security_id)
);
CREATE TABLE data_quality_issue (
  quality_issue_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES provider_attempt(attempt_id),
  normalized_version_id TEXT REFERENCES normalized_version(normalized_version_id),
  severity TEXT NOT NULL CHECK(severity IN ('warning','quarantine','blocking')),
  code TEXT NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE data_snapshot (
  data_snapshot_id TEXT PRIMARY KEY,
  scope_id TEXT NOT NULL,
  snapshot_purpose TEXT NOT NULL CHECK(snapshot_purpose IN ('research','workflow','market','chart')),
  requested_date TEXT NOT NULL,
  effective_session_date TEXT NOT NULL,
  as_of_at TEXT NOT NULL,
  market_timezone TEXT NOT NULL,
  calendar_version TEXT NOT NULL,
  query_policy_version TEXT NOT NULL,
  source_policy_version TEXT NOT NULL,
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
  UNIQUE(snapshot_purpose,as_of_at,membership_hash,query_policy_version,source_policy_version,freshness_policy_version)
);
CREATE TABLE data_snapshot_member (
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  normalized_version_id TEXT NOT NULL REFERENCES normalized_version(normalized_version_id),
  member_role TEXT NOT NULL,
  member_order INTEGER NOT NULL,
  PRIMARY KEY(data_snapshot_id,normalized_version_id),
  UNIQUE(data_snapshot_id,member_order)
);
CREATE TABLE fixture_rights_profile (
  fixture_member_id TEXT PRIMARY KEY,
  source_identity TEXT NOT NULL,
  local_storage_allowed INTEGER NOT NULL CHECK(local_storage_allowed IN (0,1)),
  deterministic_replay_allowed INTEGER NOT NULL CHECK(deterministic_replay_allowed IN (0,1)),
  repository_redistribution_allowed INTEGER NOT NULL CHECK(repository_redistribution_allowed IN (0,1)),
  packaged_distribution_allowed INTEGER NOT NULL CHECK(packaged_distribution_allowed IN (0,1)),
  terms_version TEXT NOT NULL,
  reviewed_on TEXT NOT NULL,
  raw_sha256 TEXT
);
