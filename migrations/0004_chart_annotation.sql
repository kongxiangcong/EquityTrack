CREATE TABLE chart_annotation (
  annotation_id TEXT PRIMARY KEY,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  created_at TEXT NOT NULL
);
CREATE TABLE chart_annotation_version (
  annotation_version_id TEXT PRIMARY KEY,
  annotation_id TEXT NOT NULL REFERENCES chart_annotation(annotation_id),
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  supersedes_version_id TEXT REFERENCES chart_annotation_version(annotation_version_id),
  status TEXT NOT NULL CHECK(status IN ('active','deleted')),
  interval_code TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL CHECK(adjustment_mode IN ('none','forward','backward')),
  data_snapshot_id TEXT NOT NULL REFERENCES data_snapshot(data_snapshot_id),
  factor_snapshot_id TEXT REFERENCES data_snapshot(data_snapshot_id),
  annotation_kind TEXT NOT NULL CHECK(annotation_kind IN ('trend_line','horizontal_line','note')),
  style_name TEXT NOT NULL CHECK(style_name IN ('accent','warning','neutral')),
  author_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  UNIQUE(annotation_id,version_no),
  UNIQUE(annotation_id,content_hash)
);
CREATE TABLE chart_annotation_anchor (
  annotation_version_id TEXT NOT NULL REFERENCES chart_annotation_version(annotation_version_id),
  anchor_no INTEGER NOT NULL CHECK(anchor_no >= 0),
  market_timestamp TEXT NOT NULL,
  exact_price_decimal TEXT NOT NULL,
  PRIMARY KEY(annotation_version_id,anchor_no)
);
CREATE TABLE chart_annotation_link (
  annotation_version_id TEXT NOT NULL REFERENCES chart_annotation_version(annotation_version_id),
  link_no INTEGER NOT NULL CHECK(link_no >= 0),
  link_type TEXT NOT NULL CHECK(link_type IN ('ResearchRun','Evidence','TradePlanVersion','MarketEvent')),
  link_id TEXT NOT NULL,
  resolution_status TEXT NOT NULL CHECK(resolution_status IN ('resolved','unresolved_external')),
  PRIMARY KEY(annotation_version_id,link_no)
);
CREATE TRIGGER chart_annotation_version_no_update BEFORE UPDATE ON chart_annotation_version BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_no_update BEFORE UPDATE ON chart_annotation BEGIN SELECT RAISE(ABORT,'ANNOTATION_IDENTITY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_no_delete BEFORE DELETE ON chart_annotation BEGIN SELECT RAISE(ABORT,'ANNOTATION_IDENTITY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_version_no_delete BEFORE DELETE ON chart_annotation_version BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_anchor_no_update BEFORE UPDATE ON chart_annotation_anchor BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_anchor_no_delete BEFORE DELETE ON chart_annotation_anchor BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_link_no_update BEFORE UPDATE ON chart_annotation_link BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_link_no_delete BEFORE DELETE ON chart_annotation_link BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_anchor_no_late_insert BEFORE INSERT ON chart_annotation_anchor WHEN EXISTS (SELECT 1 FROM command_receipt WHERE result_type='ChartAnnotationVersion' AND result_id=NEW.annotation_version_id) BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_link_no_late_insert BEFORE INSERT ON chart_annotation_link WHEN EXISTS (SELECT 1 FROM command_receipt WHERE result_type='ChartAnnotationVersion' AND result_id=NEW.annotation_version_id) BEGIN SELECT RAISE(ABORT,'ANNOTATION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER chart_annotation_version_lineage BEFORE INSERT ON chart_annotation_version WHEN
  (NEW.version_no=1 AND NEW.supersedes_version_id IS NOT NULL)
  OR (NEW.version_no>1 AND NOT EXISTS (
    SELECT 1 FROM chart_annotation_version previous
    WHERE previous.annotation_version_id=NEW.supersedes_version_id
      AND previous.annotation_id=NEW.annotation_id
      AND previous.version_no=NEW.version_no-1
      AND previous.version_no=(SELECT max(latest.version_no) FROM chart_annotation_version latest WHERE latest.annotation_id=NEW.annotation_id)
  ))
BEGIN SELECT RAISE(ABORT,'ANNOTATION_LINEAGE_INVALID'); END;
