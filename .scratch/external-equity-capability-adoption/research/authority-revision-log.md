# Goal authority revision log

## 2026-07-24 user update

- Authoritative file:
  `.scratch/external-equity-capability-adoption/goal_prompt.md`
- Line count after update: `506`
- SHA-256:
  `ca1148516e14c148ac247123081ce7a2237863a725192779b3b9c7241fbee41d`
- Read in full before resolving the active Wayfinder ticket.

Material execution changes:

1. The complete Goal is explicitly AFK; one ticket per Goal continuation is a
   context/commit boundary, not a user approval gate.
2. Clone/network/external-directory/dependency permissions should be requested
   once at the smallest common scope rather than repeatedly.
3. Public Equity Investing may remain precisely `external_blocked` if it is not
   essential to the canonical production path.
4. Vibe-Trading qualification must automatically use local `uv`, CPython 3.11
   and an upstream-local `.venv`, then exercise pinned stdio MCP initialization,
   tool discovery, restricted calls and hostile failure cases.
5. Docker, LLM/API keys, OAuth, broker accounts and personal data are not
   blockers.
6. Live trading, simulated order interfaces, broker adapters, order lifecycle
   and account credential management are permanently excluded; no placeholder
   interface may be retained for them.

The Map Notes and the Vibe-Trading qualification ticket were updated to encode
these standing rules. The ticket-01 upstream identity, rights and attack-surface
evidence remains valid and does not claim that Vibe runtime qualification has
already occurred.
