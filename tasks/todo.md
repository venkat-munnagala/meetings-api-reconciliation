# Event Sync Service — todo

## Design
- [x] EDA notebook with progressive discovery (notebooks/eda.ipynb)
- [x] Research: enterprise reconciliation practice (notebooks/reports/)
- [x] Design spec (docs/superpowers/specs/2026-11-09-event-sync-service-design.md)
- [x] Builder check on spec, resolve questions
- [x] Implementation plan (docs/superpowers/plans/2026-11-09-event-sync-service.md)

## Build
- [x] Project scaffold, config, single command `uv run eventsync`
- [ ] Adapters + normalisation + quality flags
- [ ] Participant resolver
- [ ] Dedupe + cascade + merge (FieldViews)
- [ ] Store + API routers
- [ ] Static frontend (meetings, detail, proposals, quality, unmatched)
- [ ] Tests pinned to EDA trap table
- [ ] README (run, approach, traps, decisions, not-built, time)
- [ ] docs/ai-collaboration index

## Review
- [ ] Verify every trap row behaves as specified
- [ ] Time log
