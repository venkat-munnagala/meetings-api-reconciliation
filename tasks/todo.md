# Event Sync Service — todo

## Design
- [x] EDA notebook with progressive discovery (notebooks/eda.ipynb)
- [x] Research: enterprise reconciliation practice (notebooks/reports/)
- [x] Design spec (docs/superpowers/specs/2026-11-09-event-sync-service-design.md)
- [x] Builder check on spec, resolve questions
- [x] Implementation plan (docs/superpowers/plans/2026-11-09-event-sync-service.md)

## Build
- [x] Project scaffold, config, single command `uv run eventsync`
- [x] Adapters + normalisation + quality flags
- [x] Participant resolver
- [x] Dedupe + cascade + merge (FieldViews)
- [x] Store + API routers
- [x] Static frontend (meetings, detail, proposals, quality, unmatched) — manually checked in browser: 28 rows, 1002 unresolved location, 4 proposals, 1003→A7
- [x] Tests pinned to EDA trap table (78 passing)
- [x] README (run, approach, traps, decisions, not-built, time)
- [x] docs/ai-collaboration index

## Review
- [x] Verify every trap row behaves as specified (one test per row; 78 passing)
- [x] Time log (README: ~8h wall-clock, split by phase)

## Review
- Pipeline: 42 records → 28 meetings (14 auto, 7 proposed, 7 singleton), 4 proposals (2 level-2, 1 level-3, 1 duplicate), 3 conflicts + 2 unresolved fields, 19 quality flags.
- Browser check done on Meetings, Proposals, Unmatched views.
- Final whole-branch review by a fresh agent: see .superpowers ledger / final message.
