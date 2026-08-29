# Atomic cutover manifest

Ticket 07 freezes the ticket 08 change unit:

- Replace `skills/SKILL.md` and old task files with account, research, valuation, planning, monitoring, and review instructions.
- Replace the CLI parser and composition wiring with the eight Application operations.
- Keep only the six domain Modules, application Interface, SQLite Adapter, Fixture Adapter, read-only Markdown projection, doctor and backup/restore.
- Delete `src/equity_research`, the superseded `trading_platform` application/domain/persistence/research/workflow/provider/Web/report code, 25 old migrations, all old tests and fixtures, report/chart/workbook/PDF scripts and assets, Web sources/dist, real-company examples, old Skill analysis/output/reference/module/script files, and unused dependencies.
- Preserve governance documents and clearly historical research material only when they are outside runtime/control-plane searches.

Any remaining caller, retired schema, duplicate persistence path, renderer, compatibility branch, or unmapped irreplaceable fact blocks the cutover.
