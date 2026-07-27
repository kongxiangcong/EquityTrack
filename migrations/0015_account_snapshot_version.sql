CREATE TABLE account_snapshot_draft (
  draft_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  revision INTEGER NOT NULL CHECK(revision > 0),
  status TEXT NOT NULL CHECK(status IN ('open','rejected','discarded','confirmed')),
  source_kind TEXT NOT NULL,
  redacted_source_ref TEXT NOT NULL,
  as_of_at TEXT NOT NULL,
  as_of_precision TEXT NOT NULL CHECK(as_of_precision IN ('date','instant')),
  timezone TEXT NOT NULL,
  session_semantics TEXT NOT NULL,
  currency TEXT NOT NULL,
  cash_state TEXT NOT NULL CHECK(cash_state IN ('known','unknown','not_applicable')),
  cash_value TEXT,
  nav_state TEXT NOT NULL CHECK(nav_state IN ('known','unknown','not_applicable')),
  nav_value TEXT,
  fees_state TEXT NOT NULL CHECK(fees_state IN ('known','unknown','not_applicable')),
  fees_value TEXT,
  previous_snapshot_version_id TEXT,
  revises_snapshot_version_id TEXT,
  corrects_snapshot_version_id TEXT,
  correction_reason TEXT,
  validation_state TEXT NOT NULL CHECK(validation_state IN ('valid','invalid')),
  validation_errors_json TEXT NOT NULL,
  capability_impacts_json TEXT NOT NULL,
  canonical_diff TEXT NOT NULL,
  canonical_diff_hash TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK((cash_state='known')=(cash_value IS NOT NULL)),
  CHECK((nav_state='known')=(nav_value IS NOT NULL)),
  CHECK((fees_state='known')=(fees_value IS NOT NULL)),
  CHECK((corrects_snapshot_version_id IS NULL) OR length(trim(correction_reason)) > 0),
  UNIQUE(account_id,revision,content_hash)
);
CREATE TABLE account_snapshot_draft_position (
  draft_id TEXT NOT NULL REFERENCES account_snapshot_draft(draft_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  total_quantity TEXT NOT NULL,
  available_quantity_state TEXT NOT NULL CHECK(available_quantity_state IN ('known','unknown','not_applicable')),
  available_quantity_value TEXT,
  cost_state TEXT NOT NULL CHECK(cost_state IN ('known','unknown','not_applicable')),
  cost_value TEXT,
  market_value_state TEXT NOT NULL CHECK(market_value_state IN ('known','unknown','not_applicable')),
  market_value_value TEXT,
  content_hash TEXT NOT NULL,
  CHECK((available_quantity_state='known')=(available_quantity_value IS NOT NULL)),
  CHECK((cost_state='known')=(cost_value IS NOT NULL)),
  CHECK((market_value_state='known')=(market_value_value IS NOT NULL)),
  PRIMARY KEY(draft_id,security_id)
);
CREATE TABLE account_snapshot_version (
  account_snapshot_version_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  source_draft_id TEXT NOT NULL UNIQUE REFERENCES account_snapshot_draft(draft_id),
  as_of_at TEXT NOT NULL,
  as_of_precision TEXT NOT NULL CHECK(as_of_precision IN ('date','instant')),
  timezone TEXT NOT NULL,
  session_semantics TEXT NOT NULL CHECK(session_semantics IN ('complete_session','intraday','legacy_unknown')),
  currency TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  redacted_source_ref TEXT NOT NULL,
  previous_snapshot_version_id TEXT REFERENCES account_snapshot_version(account_snapshot_version_id),
  revises_snapshot_version_id TEXT REFERENCES account_snapshot_version(account_snapshot_version_id),
  corrects_snapshot_version_id TEXT REFERENCES account_snapshot_version(account_snapshot_version_id),
  correction_reason TEXT,
  confirmed_by TEXT NOT NULL CHECK(confirmed_by LIKE 'user:%'),
  confirmed_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  graph_seal_hash TEXT NOT NULL UNIQUE,
  CHECK((corrects_snapshot_version_id IS NULL) OR length(trim(correction_reason)) > 0),
  UNIQUE(account_id,version_no)
);
CREATE TABLE account_snapshot_cash (
  account_snapshot_version_id TEXT PRIMARY KEY REFERENCES account_snapshot_version(account_snapshot_version_id),
  cash_state TEXT NOT NULL CHECK(cash_state IN ('known','unknown','not_applicable')),
  cash_value TEXT,
  currency TEXT NOT NULL,
  nav_state TEXT NOT NULL CHECK(nav_state IN ('known','unknown','not_applicable')),
  nav_value TEXT,
  fees_state TEXT NOT NULL CHECK(fees_state IN ('known','unknown','not_applicable')),
  fees_value TEXT,
  CHECK((cash_state='known')=(cash_value IS NOT NULL)),
  CHECK((nav_state='known')=(nav_value IS NOT NULL)),
  CHECK((fees_state='known')=(fees_value IS NOT NULL))
);
CREATE TABLE account_snapshot_position (
  account_snapshot_version_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  security_id TEXT NOT NULL REFERENCES security(security_id),
  total_quantity TEXT NOT NULL,
  available_quantity_state TEXT NOT NULL CHECK(available_quantity_state IN ('known','unknown','not_applicable')),
  available_quantity_value TEXT,
  cost_state TEXT NOT NULL CHECK(cost_state IN ('known','unknown','not_applicable')),
  cost_value TEXT,
  market_value_state TEXT NOT NULL CHECK(market_value_state IN ('known','unknown','not_applicable')),
  market_value_value TEXT,
  content_hash TEXT NOT NULL,
  CHECK((available_quantity_state='known')=(available_quantity_value IS NOT NULL)),
  CHECK((cost_state='known')=(cost_value IS NOT NULL)),
  CHECK((market_value_state='known')=(market_value_value IS NOT NULL)),
  PRIMARY KEY(account_snapshot_version_id,security_id)
);
CREATE TABLE account_snapshot_capability (
  account_snapshot_version_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  capability_key TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('available','unable')),
  reason_code TEXT,
  required_field_refs_json TEXT NOT NULL,
  PRIMARY KEY(account_snapshot_version_id,capability_key)
);
CREATE TABLE account_snapshot_transition (
  transition_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  from_snapshot_version_id TEXT REFERENCES account_snapshot_version(account_snapshot_version_id),
  to_snapshot_version_id TEXT NOT NULL UNIQUE REFERENCES account_snapshot_version(account_snapshot_version_id),
  reason TEXT NOT NULL CHECK(reason IN ('initial_confirmation','new_observation','revision','correction')),
  decision_actor TEXT NOT NULL CHECK(decision_actor LIKE 'user:%'),
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  command_invocation_id TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL,
  content_hash TEXT NOT NULL
);
CREATE TABLE account_snapshot_projection_checkpoint (
  account_id TEXT PRIMARY KEY REFERENCES account(account_id),
  account_snapshot_version_id TEXT NOT NULL UNIQUE REFERENCES account_snapshot_version(account_snapshot_version_id),
  projection_revision INTEGER NOT NULL CHECK(projection_revision > 0),
  projection_hash TEXT NOT NULL,
  advanced_at TEXT NOT NULL
);
CREATE TABLE application_event (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  event_payload_json TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE application_command_receipt (
  invocation_id TEXT PRIMARY KEY,
  command_name TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  result_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  revision_or_version_id TEXT NOT NULL,
  status TEXT NOT NULL,
  decision_actor TEXT NOT NULL,
  interaction_channel TEXT NOT NULL,
  transport_actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE account_snapshot_migration_provenance (
  account_snapshot_version_id TEXT PRIMARY KEY REFERENCES account_snapshot_version(account_snapshot_version_id),
  source_type TEXT NOT NULL,
  source_row_identity TEXT NOT NULL,
  migration_manifest_hash TEXT NOT NULL,
  migrated_at TEXT NOT NULL
);

INSERT INTO account_snapshot_draft(
  draft_id,account_id,revision,status,source_kind,redacted_source_ref,
  as_of_at,as_of_precision,timezone,session_semantics,currency,
  cash_state,cash_value,nav_state,nav_value,fees_state,fees_value,
  previous_snapshot_version_id,revises_snapshot_version_id,
  corrects_snapshot_version_id,correction_reason,validation_state,
  validation_errors_json,capability_impacts_json,canonical_diff,
  canonical_diff_hash,content_json,content_hash,created_by,created_at,updated_at
)
SELECT
  'account_snapshot_draft_' || substr(canonical_sha256('0015:' || p.portfolio_snapshot_id),1,24),
  p.account_id,
  (SELECT count(*) FROM portfolio_snapshot prior WHERE prior.account_id=p.account_id AND (prior.as_of_date < p.as_of_date OR (prior.as_of_date=p.as_of_date AND prior.portfolio_snapshot_id<=p.portfolio_snapshot_id))),
  'confirmed','legacy_broker_opening_import',
  'legacy-account-import:' || b.import_batch_id,
  p.as_of_date,'date','Asia/Shanghai','legacy_unknown',a.base_currency,
  'known',c.amount_decimal,'unknown',NULL,'unknown',NULL,
  CASE WHEN (SELECT count(*) FROM portfolio_snapshot prior WHERE prior.account_id=p.account_id AND (prior.as_of_date < p.as_of_date OR (prior.as_of_date=p.as_of_date AND prior.portfolio_snapshot_id<p.portfolio_snapshot_id)))=0 THEN NULL ELSE
    (SELECT 'account_snapshot_version_' || substr(canonical_sha256('0015:' || prior.portfolio_snapshot_id),1,24) FROM portfolio_snapshot prior WHERE prior.account_id=p.account_id AND (prior.as_of_date < p.as_of_date OR (prior.as_of_date=p.as_of_date AND prior.portfolio_snapshot_id<p.portfolio_snapshot_id)) ORDER BY prior.as_of_date DESC,prior.portfolio_snapshot_id DESC LIMIT 1)
  END,
  NULL,NULL,NULL,'valid','[]',
  '["fees_dependent_rules_unable","nav_dependent_rules_unable"]',
  '{"migration":"0015","source":"legacy_account_opening"}',
  canonical_sha256('0015-diff:' || p.portfolio_snapshot_id),
  json_object('account_id',p.account_id,'as_of_at',p.as_of_date,'source_kind','legacy_broker_opening_import','source_snapshot_hash',p.source_snapshot_hash),
  canonical_sha256('0015-content:' || p.portfolio_snapshot_id || ':' || p.source_snapshot_hash),
  'migration:0015',
  json_extract(b.evidence_json,'$.confirmation.confirmed_at'),
  json_extract(b.evidence_json,'$.confirmation.confirmed_at')
FROM portfolio_snapshot p
JOIN account a USING(account_id)
JOIN account_import_batch b ON b.account_id=p.account_id AND b.source_snapshot_hash=p.source_snapshot_hash
JOIN account_cash_opening c USING(account_id)
ORDER BY p.account_id,p.as_of_date,p.portfolio_snapshot_id;

INSERT INTO account_snapshot_draft_position
SELECT
  'account_snapshot_draft_' || substr(canonical_sha256('0015:' || s.portfolio_snapshot_id),1,24),
  p.security_id,p.quantity_decimal,'known',p.available_decimal,
  CASE WHEN CAST(l.cost_price_decimal AS TEXT) GLOB '*[^0-9.-]*' THEN 'unknown' ELSE 'known' END,
  CASE WHEN CAST(l.cost_price_decimal AS TEXT) GLOB '*[^0-9.-]*' THEN NULL ELSE l.cost_price_decimal END,
  'known',o.source_market_value_decimal,
  canonical_sha256('0015-position:' || s.portfolio_snapshot_id || ':' || p.position_id || ':' || p.quantity_decimal || ':' || p.available_decimal || ':' || coalesce(l.cost_price_decimal,'unknown') || ':' || o.source_market_value_decimal)
FROM portfolio_snapshot s
JOIN account_position p USING(account_id)
JOIN account_position_lot l USING(position_id)
JOIN account_position_observation o USING(position_id);

INSERT INTO account_snapshot_version
SELECT
  'account_snapshot_version_' || substr(canonical_sha256('0015:' || p.portfolio_snapshot_id),1,24),
  p.account_id,
  d.revision,
  d.draft_id,p.as_of_date,'date','Asia/Shanghai','legacy_unknown',a.base_currency,
  'legacy_broker_opening_import',d.redacted_source_ref,
  d.previous_snapshot_version_id,NULL,NULL,NULL,
  'user:legacy-confirmation',
  json_extract(b.evidence_json,'$.confirmation.confirmed_at'),
  d.content_hash,
  canonical_sha256('0015-seal:' || d.content_hash || ':' || p.account_id || ':' || d.revision)
FROM portfolio_snapshot p
JOIN account a USING(account_id)
JOIN account_import_batch b ON b.account_id=p.account_id AND b.source_snapshot_hash=p.source_snapshot_hash
JOIN account_snapshot_draft d ON d.account_id=p.account_id AND d.as_of_at=p.as_of_date
ORDER BY p.account_id,p.as_of_date,p.portfolio_snapshot_id;

INSERT INTO account_snapshot_cash
SELECT v.account_snapshot_version_id,d.cash_state,d.cash_value,d.currency,
       d.nav_state,d.nav_value,d.fees_state,d.fees_value
FROM account_snapshot_version v JOIN account_snapshot_draft d ON d.draft_id=v.source_draft_id;

INSERT INTO account_snapshot_position
SELECT v.account_snapshot_version_id,p.security_id,p.total_quantity,
       p.available_quantity_state,p.available_quantity_value,
       p.cost_state,p.cost_value,p.market_value_state,p.market_value_value,p.content_hash
FROM account_snapshot_version v
JOIN account_snapshot_draft_position p ON p.draft_id=v.source_draft_id;

INSERT INTO account_snapshot_capability
SELECT account_snapshot_version_id,'cash_rules','available',NULL,'["cash"]'
FROM account_snapshot_cash WHERE cash_state='known';
INSERT INTO account_snapshot_capability
SELECT account_snapshot_version_id,'nav_rules','unable','OPTIONAL_OPERAND_UNKNOWN','["nav"]'
FROM account_snapshot_cash WHERE nav_state<>'known';
INSERT INTO account_snapshot_capability
SELECT account_snapshot_version_id,'fees_rules','unable','OPTIONAL_OPERAND_UNKNOWN','["fees"]'
FROM account_snapshot_cash WHERE fees_state<>'known';
INSERT INTO account_snapshot_capability
SELECT account_snapshot_version_id,'total_quantity:' || security_id,'available',NULL,
       json_array('positions.' || security_id || '.total_quantity')
FROM account_snapshot_position;
INSERT INTO account_snapshot_capability
SELECT account_snapshot_version_id,'available_quantity:' || security_id,
       CASE available_quantity_state WHEN 'known' THEN 'available' ELSE 'unable' END,
       CASE available_quantity_state WHEN 'known' THEN NULL ELSE 'OPTIONAL_OPERAND_UNKNOWN' END,
       json_array('positions.' || security_id || '.available_quantity')
FROM account_snapshot_position;

INSERT INTO account_snapshot_transition
SELECT
  'account_snapshot_transition_' || substr(canonical_sha256('0015:' || v.account_snapshot_version_id),1,24),
  v.account_id,v.previous_snapshot_version_id,v.account_snapshot_version_id,
  CASE WHEN v.previous_snapshot_version_id IS NULL THEN 'initial_confirmation' ELSE 'new_observation' END,
  'user:legacy-confirmation','migration','system:migration-0015',
  json_extract(b.evidence_json,'$.confirmation.invocation_id') || ':migration-0015',
  v.confirmed_at,
  canonical_sha256('0015-transition:' || v.account_snapshot_version_id || ':' || coalesce(v.previous_snapshot_version_id,'initial'))
FROM account_snapshot_version v
JOIN account_snapshot_draft d ON d.draft_id=v.source_draft_id
JOIN account_import_batch b ON d.redacted_source_ref='legacy-account-import:' || b.import_batch_id;

INSERT INTO account_snapshot_projection_checkpoint
SELECT v.account_id,v.account_snapshot_version_id,v.version_no,
       canonical_sha256('0015-projection:' || v.account_id || ':' || v.account_snapshot_version_id || ':' || v.version_no),
       v.confirmed_at
FROM account_snapshot_version v
WHERE NOT EXISTS(
  SELECT 1 FROM account_snapshot_version later
  WHERE later.account_id=v.account_id AND later.version_no>v.version_no
);

INSERT INTO application_event
SELECT
  'application_event_' || substr(canonical_sha256('0015:' || v.account_snapshot_version_id),1,24),
  'AccountSnapshotConfirmed','AccountSnapshotVersion',v.account_snapshot_version_id,
  json_object('account_id',v.account_id,'account_snapshot_version_id',v.account_snapshot_version_id,'migration','0015'),
  v.confirmed_at,
  canonical_sha256('0015-event:' || v.account_snapshot_version_id)
FROM account_snapshot_version v;

INSERT INTO application_command_receipt
SELECT
  t.command_invocation_id,'account_snapshot.confirm@1',
  canonical_sha256('0015-request:' || v.source_draft_id),
  'AccountSnapshotVersion',v.account_id,v.account_snapshot_version_id,
  'succeeded',t.decision_actor,t.interaction_channel,t.transport_actor,v.confirmed_at
FROM account_snapshot_version v
JOIN account_snapshot_transition t ON t.to_snapshot_version_id=v.account_snapshot_version_id;

INSERT INTO account_snapshot_migration_provenance
SELECT
  v.account_snapshot_version_id,'portfolio_snapshot',
  p.portfolio_snapshot_id || ':' || c.source_row_identity,
  canonical_sha256('0015-manifest:' || p.portfolio_snapshot_id || ':' || p.source_snapshot_hash || ':' || c.source_row_identity || ':' || v.graph_seal_hash),
  v.confirmed_at
FROM account_snapshot_version v
JOIN account_snapshot_draft d ON d.draft_id=v.source_draft_id
JOIN portfolio_snapshot p ON p.account_id=v.account_id AND p.as_of_date=v.as_of_at
JOIN account_cash_opening c USING(account_id);

ALTER TABLE plan_account_snapshot_reference RENAME TO plan_account_snapshot_reference_legacy_0015;
CREATE TABLE plan_account_snapshot_reference (
  plan_version_id TEXT PRIMARY KEY REFERENCES trade_plan_version(plan_version_id),
  snapshot_type TEXT NOT NULL CHECK(snapshot_type='AccountSnapshotVersion'),
  snapshot_id TEXT NOT NULL REFERENCES account_snapshot_version(account_snapshot_version_id),
  account_id TEXT NOT NULL REFERENCES account(account_id),
  snapshot_as_of TEXT NOT NULL,
  reconciliation_status TEXT NOT NULL,
  context_json TEXT NOT NULL,
  context_hash TEXT NOT NULL,
  UNIQUE(plan_version_id,snapshot_type,snapshot_id)
);
INSERT INTO plan_account_snapshot_reference
SELECT r.plan_version_id,'AccountSnapshotVersion',v.account_snapshot_version_id,
       r.account_id,r.snapshot_as_of,r.reconciliation_status,r.context_json,r.context_hash
FROM plan_account_snapshot_reference_legacy_0015 r
JOIN portfolio_snapshot p ON r.snapshot_type='PortfolioSnapshot' AND p.portfolio_snapshot_id=r.snapshot_id
JOIN account_snapshot_version v ON v.account_id=p.account_id AND v.as_of_at=p.as_of_date;
DROP TABLE plan_account_snapshot_reference_legacy_0015;

CREATE TRIGGER account_snapshot_draft_confirmed_no_update
BEFORE UPDATE ON account_snapshot_draft
WHEN OLD.status='confirmed'
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_draft_confirmed_no_delete
BEFORE DELETE ON account_snapshot_draft
WHEN OLD.status='confirmed'
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_version_no_update BEFORE UPDATE ON account_snapshot_version
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_version_no_delete BEFORE DELETE ON account_snapshot_version
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_cash_no_update BEFORE UPDATE ON account_snapshot_cash
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_cash_no_delete BEFORE DELETE ON account_snapshot_cash
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_position_no_update BEFORE UPDATE ON account_snapshot_position
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_position_no_delete BEFORE DELETE ON account_snapshot_position
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_capability_no_update BEFORE UPDATE ON account_snapshot_capability
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_capability_no_delete BEFORE DELETE ON account_snapshot_capability
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_transition_no_update BEFORE UPDATE ON account_snapshot_transition
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_transition_no_delete BEFORE DELETE ON account_snapshot_transition
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_event_no_update BEFORE UPDATE ON application_event
BEGIN SELECT RAISE(ABORT,'APPLICATION_EVENT_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_event_no_delete BEFORE DELETE ON application_event
BEGIN SELECT RAISE(ABORT,'APPLICATION_EVENT_IMMUTABLE'); END;
CREATE TRIGGER application_command_receipt_no_update BEFORE UPDATE ON application_command_receipt
BEGIN SELECT RAISE(ABORT,'APPLICATION_COMMAND_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER application_command_receipt_no_delete BEFORE DELETE ON application_command_receipt
BEGIN SELECT RAISE(ABORT,'APPLICATION_COMMAND_RECEIPT_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_migration_provenance_no_update BEFORE UPDATE ON account_snapshot_migration_provenance
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_MIGRATION_PROVENANCE_IMMUTABLE'); END;
CREATE TRIGGER account_snapshot_migration_provenance_no_delete BEFORE DELETE ON account_snapshot_migration_provenance
BEGIN SELECT RAISE(ABORT,'ACCOUNT_SNAPSHOT_MIGRATION_PROVENANCE_IMMUTABLE'); END;
