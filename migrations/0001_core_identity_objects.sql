CREATE TABLE security (
  security_id TEXT PRIMARY KEY,
  currency TEXT NOT NULL
);
CREATE TABLE security_identifier (
  security_identifier_id TEXT PRIMARY KEY,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  market TEXT NOT NULL,
  code TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_from_precision TEXT NOT NULL CHECK(valid_from_precision = 'date'),
  valid_to TEXT,
  valid_to_precision TEXT CHECK(valid_to_precision IS NULL OR valid_to_precision = 'date'),
  UNIQUE(market, code, valid_from)
);
CREATE TABLE watchlist (
  watchlist_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE watchlist_item (
  watchlist_item_id TEXT PRIMARY KEY,
  watchlist_id TEXT NOT NULL REFERENCES watchlist(watchlist_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  created_at TEXT NOT NULL,
  UNIQUE(watchlist_id, security_id)
);
CREATE TABLE object_blob (
  sha256 TEXT PRIMARY KEY,
  size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
  relative_path TEXT NOT NULL UNIQUE
);
CREATE TABLE artifact (artifact_id TEXT PRIMARY KEY, object_sha256 TEXT NOT NULL REFERENCES object_blob(sha256), media_type TEXT NOT NULL, schema_version TEXT NOT NULL);
CREATE TABLE artifact_relation (artifact_id TEXT NOT NULL REFERENCES artifact(artifact_id), relation_type TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, PRIMARY KEY(artifact_id, relation_type, target_type, target_id));
CREATE TABLE command_receipt (
  invocation_id TEXT PRIMARY KEY,
  command_name TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  result_type TEXT NOT NULL,
  result_id TEXT NOT NULL
);
INSERT INTO watchlist(watchlist_id, name) VALUES ('watchlist_default', '观察列表');
