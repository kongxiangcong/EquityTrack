CREATE TABLE portfolio_risk_policy_version (
  portfolio_risk_policy_version_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES account(account_id),
  version_no INTEGER NOT NULL CHECK(version_no > 0),
  schema_version TEXT NOT NULL CHECK(schema_version='PortfolioRiskPolicy@1'),
  currency TEXT NOT NULL CHECK(currency='CNY'),
  previous_portfolio_risk_policy_version_id TEXT
    REFERENCES portfolio_risk_policy_version(portfolio_risk_policy_version_id)
    UNIQUE,
  single_security_exposure TEXT NOT NULL CHECK(length(single_security_exposure) > 0),
  industry_exposure TEXT NOT NULL CHECK(length(industry_exposure) > 0),
  gross_exposure TEXT NOT NULL CHECK(length(gross_exposure) > 0),
  minimum_cash TEXT NOT NULL CHECK(length(minimum_cash) > 0),
  single_plan_loss TEXT NOT NULL CHECK(length(single_plan_loss) > 0),
  aggregate_active_plan_loss TEXT NOT NULL CHECK(length(aggregate_active_plan_loss) > 0),
  drawdown_review TEXT NOT NULL CHECK(length(drawdown_review) > 0),
  drawdown_freeze TEXT NOT NULL CHECK(length(drawdown_freeze) > 0),
  plan_daily_liquidity TEXT NOT NULL CHECK(length(plan_daily_liquidity) > 0),
  position_daily_liquidity TEXT NOT NULL CHECK(length(position_daily_liquidity) > 0),
  confirmed_by TEXT NOT NULL CHECK(confirmed_by LIKE 'user:%'),
  confirmed_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  identity_hash TEXT NOT NULL UNIQUE,
  command_invocation_id TEXT NOT NULL UNIQUE,
  CHECK(
    (version_no=1 AND previous_portfolio_risk_policy_version_id IS NULL)
    OR
    (version_no>1 AND previous_portfolio_risk_policy_version_id IS NOT NULL)
  ),
  UNIQUE(account_id,version_no)
);

CREATE INDEX portfolio_risk_policy_latest
ON portfolio_risk_policy_version(account_id,version_no DESC);

CREATE TRIGGER portfolio_risk_policy_no_update
BEFORE UPDATE ON portfolio_risk_policy_version
BEGIN
  SELECT RAISE(ABORT,'PORTFOLIO_RISK_POLICY_IMMUTABLE');
END;

CREATE TRIGGER portfolio_risk_policy_no_delete
BEFORE DELETE ON portfolio_risk_policy_version
BEGIN
  SELECT RAISE(ABORT,'PORTFOLIO_RISK_POLICY_IMMUTABLE');
END;
