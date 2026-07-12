CREATE TABLE update_authorization (
  update_authorization_id TEXT PRIMARY KEY,
  invocation_id TEXT NOT NULL UNIQUE,
  security_id TEXT NOT NULL REFERENCES security(security_id),
  requested_date TEXT NOT NULL,
  effective_session_date TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope='refresh_frozen_inputs'),
  created_at TEXT NOT NULL
);
CREATE TRIGGER update_authorization_no_update BEFORE UPDATE ON update_authorization BEGIN SELECT RAISE(ABORT,'UPDATE_AUTHORIZATION_IMMUTABLE'); END;
CREATE TRIGGER update_authorization_no_delete BEFORE DELETE ON update_authorization BEGIN SELECT RAISE(ABORT,'UPDATE_AUTHORIZATION_IMMUTABLE'); END;
