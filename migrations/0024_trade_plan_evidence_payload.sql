DROP TRIGGER trade_plan_evidence_no_late_insert;
DROP TRIGGER trade_plan_evidence_no_update;
DROP TRIGGER trade_plan_evidence_no_delete;

ALTER TABLE trade_plan_evidence_reference
RENAME TO trade_plan_evidence_reference_legacy_0024;

CREATE TABLE trade_plan_evidence_reference (
  plan_version_id TEXT NOT NULL REFERENCES trade_plan_version(plan_version_id),
  ref_order INTEGER NOT NULL CHECK(ref_order >= 0),
  ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  resolution_status TEXT NOT NULL,
  reference_json TEXT NOT NULL
    CHECK(json_valid(reference_json) AND json_type(reference_json)='object'),
  content_hash TEXT NOT NULL,
  CHECK(json_extract(reference_json,'$.ref_type')=ref_type),
  CHECK(json_extract(reference_json,'$.ref_id')=ref_id),
  CHECK(json_extract(reference_json,'$.resolution_status')=resolution_status),
  CHECK(json_extract(reference_json,'$.content_hash')=content_hash),
  PRIMARY KEY(plan_version_id,ref_order)
);

INSERT INTO trade_plan_evidence_reference(
  plan_version_id,
  ref_order,
  ref_type,
  ref_id,
  resolution_status,
  reference_json,
  content_hash
)
SELECT
  legacy.plan_version_id,
  legacy.ref_order,
  legacy.ref_type,
  legacy.ref_id,
  legacy.resolution_status,
  CASE
    WHEN version.legacy_read_only=1 THEN json_object(
      'content_hash',legacy.content_hash,
      'ref_id',legacy.ref_id,
      'ref_type',legacy.ref_type,
      'resolution_status',legacy.resolution_status
    )
    ELSE (
      SELECT json_extract(
        draft.proposed_graph_json,
        '$.evidence_references[' || legacy.ref_order || ']'
      )
      FROM user_approval_receipt receipt
      JOIN trade_plan_draft draft ON draft.draft_id=receipt.draft_id
      WHERE receipt.user_approval_receipt_id=
        version.user_approval_receipt_id
        AND json_extract(
          draft.proposed_graph_json,
          '$.version.plan_version_id'
        )=legacy.plan_version_id
        AND json_extract(
          draft.proposed_graph_json,
          '$.evidence_references[' || legacy.ref_order || '].ref_type'
        )=legacy.ref_type
        AND json_extract(
          draft.proposed_graph_json,
          '$.evidence_references[' || legacy.ref_order || '].ref_id'
        )=legacy.ref_id
        AND json_extract(
          draft.proposed_graph_json,
          '$.evidence_references[' || legacy.ref_order
          || '].resolution_status'
        )=legacy.resolution_status
        AND json_extract(
          draft.proposed_graph_json,
          '$.evidence_references[' || legacy.ref_order
          || '].content_hash'
        )=legacy.content_hash
    )
  END,
  legacy.content_hash
FROM trade_plan_evidence_reference_legacy_0024 legacy
JOIN trade_plan_version version USING(plan_version_id);

DROP TABLE trade_plan_evidence_reference_legacy_0024;

CREATE TRIGGER trade_plan_evidence_no_late_insert
BEFORE INSERT ON trade_plan_evidence_reference
WHEN (
  SELECT graph_sealed
  FROM trade_plan_version
  WHERE plan_version_id=NEW.plan_version_id
)=1
BEGIN
  SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
END;

CREATE TRIGGER trade_plan_evidence_no_update
BEFORE UPDATE ON trade_plan_evidence_reference
BEGIN
  SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
END;

CREATE TRIGGER trade_plan_evidence_no_delete
BEFORE DELETE ON trade_plan_evidence_reference
BEGIN
  SELECT RAISE(ABORT,'TRADE_PLAN_GRAPH_IMMUTABLE');
END;
