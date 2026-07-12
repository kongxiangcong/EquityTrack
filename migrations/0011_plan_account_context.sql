CREATE TABLE plan_account_snapshot_reference (
  plan_version_id TEXT PRIMARY KEY REFERENCES trade_plan_version(plan_version_id),
  snapshot_type TEXT NOT NULL CHECK(snapshot_type IN ('AccountHistorySnapshot','PortfolioSnapshot')),
  snapshot_id TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  snapshot_as_of TEXT NOT NULL,
  reconciliation_status TEXT NOT NULL,
  context_json TEXT NOT NULL,
  context_hash TEXT NOT NULL,
  UNIQUE(plan_version_id,snapshot_type,snapshot_id)
);
CREATE TRIGGER account_position_immutable BEFORE UPDATE ON account_position BEGIN SELECT RAISE(ABORT,'ACCOUNT_POSITION_IMMUTABLE'); END;
CREATE TRIGGER account_position_delete_immutable BEFORE DELETE ON account_position BEGIN SELECT RAISE(ABORT,'ACCOUNT_POSITION_IMMUTABLE'); END;
CREATE TRIGGER account_position_lot_immutable BEFORE UPDATE ON account_position_lot BEGIN SELECT RAISE(ABORT,'ACCOUNT_POSITION_LOT_IMMUTABLE'); END;
CREATE TRIGGER account_position_lot_delete_immutable BEFORE DELETE ON account_position_lot BEGIN SELECT RAISE(ABORT,'ACCOUNT_POSITION_LOT_IMMUTABLE'); END;
CREATE TRIGGER portfolio_snapshot_immutable BEFORE UPDATE ON portfolio_snapshot BEGIN SELECT RAISE(ABORT,'PORTFOLIO_SNAPSHOT_IMMUTABLE'); END;
CREATE TRIGGER portfolio_snapshot_delete_immutable BEFORE DELETE ON portfolio_snapshot BEGIN SELECT RAISE(ABORT,'PORTFOLIO_SNAPSHOT_IMMUTABLE'); END;
