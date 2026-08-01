UPDATE plan_confirmation_challenge
SET status='superseded'
WHERE status='issued'
  AND draft_id IN (
    SELECT draft_id
    FROM trade_plan_draft
    WHERE status='open'
      AND json_extract(proposed_graph_json,'$.schema_version')='TradePlanGraph@1'
  );

UPDATE trade_plan_draft
SET proposed_graph_json=json_set(
      json_remove(
        proposed_graph_json,
        '$.version.confirmed_at',
        '$.version.user_approval_receipt_id'
      ),
      '$.schema_version','TradePlanDraftGraph@1',
      '$.version.schema_version','ProposedTradePlanVersion@1'
    )
WHERE status='open'
  AND json_extract(proposed_graph_json,'$.schema_version')='TradePlanGraph@1';

UPDATE trade_plan_draft
SET content_hash=canonical_sha256(
  json_object(
    'canonicalization_version','canonical-json@1',
    'value',json_object(
      'account_id',account_id,
      'based_on_version_id',based_on_version_id,
      'content',json(content_json),
      'parameters',json(parameters_json),
      'proposed_graph',json_object(
        'account_snapshot_version_id',json_extract(proposed_graph_json,'$.version.account_snapshot_version_id'),
        'ast_version',json_extract(proposed_graph_json,'$.version.ast_version'),
        'conflict_policy_version',json_extract(proposed_graph_json,'$.version.conflict_policy_version'),
        'data_snapshot_id',json_extract(proposed_graph_json,'$.version.data_snapshot_id'),
        'evaluator_policy_version',json_extract(proposed_graph_json,'$.version.evaluator_policy_version'),
        'graph_seal_hash',json_extract(proposed_graph_json,'$.version.graph_seal_hash'),
        'horizon_end',json_extract(proposed_graph_json,'$.version.horizon_end'),
        'horizon_start',json_extract(proposed_graph_json,'$.version.horizon_start'),
        'investment_thesis_version_id',json_extract(proposed_graph_json,'$.version.investment_thesis_version_id'),
        'metric_catalog_version',json_extract(proposed_graph_json,'$.version.metric_catalog_version'),
        'plan_id',json_extract(proposed_graph_json,'$.version.plan_id'),
        'plan_version_id',json_extract(proposed_graph_json,'$.version.plan_version_id'),
        'review_by',json_extract(proposed_graph_json,'$.version.review_by'),
        'risk_policy_version_id',json_extract(proposed_graph_json,'$.version.risk_policy_version_id'),
        'schema_version','TradePlanDraftGraph@1',
        'strategy_version_id',json_extract(proposed_graph_json,'$.version.strategy_version_id'),
        'supersedes_version_id',json_extract(proposed_graph_json,'$.version.supersedes_version_id'),
        'version_content_hash',json_extract(proposed_graph_json,'$.version.content_hash'),
        'version_no',json_extract(proposed_graph_json,'$.version.version_no')
      ),
      'security_id',security_id,
      'strategy_version_id',strategy_version_id
    )
  )
)
WHERE status='open'
  AND json_extract(proposed_graph_json,'$.schema_version')='TradePlanDraftGraph@1';

CREATE TRIGGER trade_plan_draft_graph_type_insert
BEFORE INSERT ON trade_plan_draft
WHEN NEW.status='open' AND (
  json_extract(NEW.proposed_graph_json,'$.schema_version')<>'TradePlanDraftGraph@1'
  OR json_extract(NEW.proposed_graph_json,'$.version.schema_version')<>'ProposedTradePlanVersion@1'
  OR json_type(NEW.proposed_graph_json,'$.version.confirmed_at') IS NOT NULL
  OR json_type(NEW.proposed_graph_json,'$.version.user_approval_receipt_id') IS NOT NULL
)
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_DRAFT_GRAPH_INVALID'); END;

CREATE TRIGGER trade_plan_draft_graph_type_update
BEFORE UPDATE OF proposed_graph_json ON trade_plan_draft
WHEN NEW.status='open' AND (
  json_extract(NEW.proposed_graph_json,'$.schema_version')<>'TradePlanDraftGraph@1'
  OR json_extract(NEW.proposed_graph_json,'$.version.schema_version')<>'ProposedTradePlanVersion@1'
  OR json_type(NEW.proposed_graph_json,'$.version.confirmed_at') IS NOT NULL
  OR json_type(NEW.proposed_graph_json,'$.version.user_approval_receipt_id') IS NOT NULL
)
BEGIN SELECT RAISE(ABORT,'TRADE_PLAN_DRAFT_GRAPH_INVALID'); END;
