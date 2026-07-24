# Public Equity Investing upstream identity and availability audit

Captured at: `2026-07-24T09:56:28Z`

## Scope

This establishes identity, current availability, licensing/data-rights limits, and the disclosed attack surface for ticket 01. It does not perform the later black-box research-quality evaluation.

## Canonical identity

| Field | Evidence |
|---|---|
| Product | `Public Equity Investing`, made by OpenAI |
| Catalog | <https://openai.com/business/plugins/public-equity-investing/> |
| Hosted share target | <https://chatgpt.com/plugins/share/8f2f2fb7215f4688a0853afd038f2a1a> |
| Announcement | <https://openai.com/index/codex-for-every-role-tool-workflow/> |
| Delivery form | Hosted role-specific Codex/ChatGPT plugin for research, diligence workflows and investment-material drafting with human review |
| Source commit/hash | Not disclosed; no reproducible source commit or artifact hash is available |
| License/NOTICE | No source-code license or NOTICE is disclosed for the hosted plugin; product terms/privacy are not an open-source grant |

The official announcement says role-specific plugins bundle apps, skills, instructions and workflows, and says this plugin can use information from Moody's, Daloopa, Datasite, FactSet, LSEG, S&P, PitchBook and Hebbia. This is a capability statement, not proof of this user's entitlements and not permission to cache, persist, derive or redistribute those providers' data.

The public `openai/role-specific-plugins` template repository currently lists Sales, Data Analytics and Product Design templates, not Public Equity Investing: <https://github.com/openai/role-specific-plugins>. Its MIT license therefore does not license this separately hosted plugin.

## Current Plugin Management evidence

The exact reference `Public Equity Investing` was passed to Plugin Management:

```text
tool: plugin_management.get_plugin_dependencies
status: failed
error_code: plugin_not_found
message: plugin_reference did not identify a public global listed plugin with a current release
```

Tool discovery was also attempted for the documented `api_tool.search_plugins -> api_tool.suggest_installs` flow. The current Codex surface exposed dependency/permission/uninstall operations but no callable catalog-search or install-suggestion operation. No install, connection or invocation was fabricated.

The official catalog and announcement prove the product exists, while also stating that role plugins roll out by supported region/workspace and that Business/Enterprise admins control underlying apps. Current plan, region, role, workspace policy, app enablement and provider entitlements are not visible here.

**Current availability:** `external_blocked`.

## Disclosed attack surface

First-party app behavior and controls are documented at <https://help.openai.com/en/articles/11487775-connectors-in-chatgpt>.

| Surface | Evidence and required control |
|---|---|
| Skills/instructions/workflows | Keep only in the Codex control plane; never import hidden prompts into business runtime. |
| Underlying apps | Exact manifest is unavailable. No app access is approved for production. |
| Read/search/deep research | Apps may retrieve connected data. Do not supply personal account data, secrets, local data roots or unredacted private artifacts. |
| Sync/indexing | Some apps can index data. Deny until retention, deletion, provenance and rights are known. |
| Write actions | Apps may modify external systems. This Goal needs none; deny them. |
| Permissions | Workspace controls and approval modes constrain use but do not replace repository financial/privacy/source gates. |
| Commercial sources | Provider names do not prove entitlement, PIT semantics, authority, redistribution rights or source-manifest sufficiency. |
| Investment language | Official examples explicitly request add/trim/exit, sizing, target price and recommendation. Formal outputs must reject these unless the repository's independent explicit rating gate passes. |

## Terms and data-rights profile

| Data class | Rights evidence | Result |
|---|---|---|
| Hosted plugin implementation | Closed hosted product, no disclosed source license/hash | Control-plane use only if later available; never vendor or make a runtime dependency |
| OpenAI processing | OpenAI terms/privacy and actual workspace controls apply | Personal financial data and secrets remain prohibited |
| Named commercial-provider content | Provider-specific entitlements and terms are not in the catalog | No established cache, persistence, derivation, redistribution or production-source right |
| User-supplied public filings/notes | Rights depend on original official sources and workspace handling | Later black-box comparison may use only a frozen, non-personal source manifest |

## Ticket-01 conclusion

1. Identity is locked to the OpenAI-hosted catalog and share target; there is no qualified source commit/hash.
2. Availability is `external_blocked` with exact `plugin_not_found` evidence.
3. Unknown app manifest, entitlements, retention and provider terms block every production/data-authority role.
4. The only safe candidate role is Codex control-plane research structure and quality comparison. tradingSystem continues to own typed Evidence, Forecast, valuation, financial-output policy, persistence and presentation.
5. Official examples demonstrate a concrete output-policy hazard, which ticket 03 must test with a frozen non-personal manifest if availability changes.
