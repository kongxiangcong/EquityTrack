CREATE TABLE terminal_financial_statement_version (
  normalized_version_id TEXT PRIMARY KEY REFERENCES normalized_version,
  security_id TEXT NOT NULL REFERENCES security,
  statement_kind TEXT NOT NULL CHECK(
    statement_kind IN ('income','balancesheet','cashflow')
  ),
  period_end TEXT NOT NULL,
  report_type TEXT NOT NULL,
  update_flag TEXT NOT NULL,
  currency TEXT NOT NULL,
  accounting_standard TEXT NOT NULL,
  extracted_fields_json TEXT NOT NULL,
  statement_identity_hash TEXT NOT NULL UNIQUE
);

CREATE TRIGGER terminal_financial_statement_no_update
BEFORE UPDATE ON terminal_financial_statement_version
BEGIN SELECT RAISE(ABORT,'TERMINAL_FINANCIAL_STATEMENT_IMMUTABLE'); END;

CREATE TRIGGER terminal_financial_statement_no_delete
BEFORE DELETE ON terminal_financial_statement_version
BEGIN SELECT RAISE(ABORT,'TERMINAL_FINANCIAL_STATEMENT_IMMUTABLE'); END;
