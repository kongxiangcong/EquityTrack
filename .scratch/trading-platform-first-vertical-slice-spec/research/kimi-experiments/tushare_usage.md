# Tushare-compatible gateway usage boundary

Status: approved local credential connection seam

The Tushare-compatible gateway used by this repository is not the official
`tushare.pro` host. Preserve that provider identity in provenance.

## Credential and endpoint handling

- `TUSHARE_TOKEN` is the logical credential scope. A present process variable
  is the explicit override; otherwise Windows reads the namespaced Credential
  Manager target `tradingSystem/TUSHARE_TOKEN`.
- The approved adapter owns the fixed gateway destination and credential-source
  precedence; callers must not supply or override either in a job, command,
  payload, source file, test fixture, artifact, or database row.
- Never commit, print, log, archive, or render the credential value or private
  endpoint parameters.
- Do not ask the user to paste the credential into chat or a command line.
- `ProviderJob@2` contains only `provider_id`, `adapter_version`, and
  `credential_env`; the credential value is resolved only in memory and is never
  persisted by the platform.

## Qualification boundary

A configured gateway or HTTP success is not qualification. Use the canonical
`provider-qualify` application route and retain the real provider identity,
business status, coverage, row counts, PIT semantics, quality result, source
policy, and persisted qualification receipt.

Kimi Datasource remains a Codex/Skill control-plane discovery and cross-check
tool. It is not a business-runtime provider and cannot supply official
disclosure authority.
