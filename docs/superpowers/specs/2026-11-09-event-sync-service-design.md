# Event Sync Service — Design

Date: 2026-11-09
Status: draft for builder review
Inputs: `problem_statement.md`, `data/crm_events.json` (20 rows), `data/calendar_events.json` (22 rows), `notebooks/eda.ipynb`, `notebooks/reports/Enterprise dirty record reconciliation.md`

## 1. Intent

A small internal service that ingests two exports of a sales team's client meetings (a CRM export and a calendar export), decides which records describe the same real-world meeting, and serves one reconciled list through a REST API and a simple web page. The reconciled list is a **source of truth built on both inputs**: it never discards a source value, never hides a disagreement behind a merged value, and never merges two records on a hunch about how people behave. Where the data alone cannot prove two records are one meeting, the service shows both and says why it stopped short.

The take-home that motivates this weighs the README as heavily as the code and calibrates against honest time spent. The design therefore favours explainable rules over clever scoring, and describes rather than builds anything an enterprise deployment would add later.

## 2. Goals, non-goals, anti-goals

Goals
- Ingest both files, normalise them to one canonical shape, keep the raw records.
- Match records across sources with a transparent rule cascade; every match states which rule fired and on what evidence.
- Surface within-source duplicates, field conflicts, malformed data and unmatched records instead of resolving them silently.
- Serve meetings, conflicts, proposals, quality flags, raw records and stats over REST.
- Show meetings in a browser with per-field source provenance and conflict status.
- Start with one command. README explains setup, approach, every key decision, and time spent. AI-collaboration artefacts are included.

Non-goals (described in the README, not built)
- Persistence beyond process memory; a database; migrations.
- A scheduler or queue. Sync is on demand.
- Confirm/reject endpoints for proposals and a persisted decisions ledger. Proposals are read-only in this version; the ledger design is documented.
- Authentication, multi-tenancy, rate limiting, deployment packaging.
- Adapters for systems other than the two provided files.
- Probabilistic (Fellegi–Sunter style) scoring or ML matching.

Anti-goals (would make this a failure even if it works)
- Merging two records because "a firm meets a client once a day" or any other behavioural assumption.
- Coercing a malformed value into a plausible one without a flag (for example trimming a UTC `Z` and treating the time as local).
- A frontend that shows one merged value per field with no way to see the other source.
- Infrastructure that adds a startup failure mode without changing what the reviewer can learn.

## 3. Constraints

- Local timezone for naive timestamps is `America/New_York`. It is configuration, echoed by `/stats`.
- Inputs are the two JSON files. Upstream APIs are simulated by reading files.
- Single process, single command, no network dependencies at runtime.
- Python 3.12, `uv` for environment and run command. (My call; the brief allows any stack. Chosen for pydantic typing at the boundary and because the EDA already lives in Python.)

## 4. What the data contains (from the EDA)

Shape: CRM is flat, 12 columns, date and time in separate naive fields, owner as a display name, client as name + company. Calendar is 11 columns, one nested `attendees` list of emails, single ISO `start_time`/`end_time`, organizer as email. No shared key. All times sit on a :00/:30 grid; seconds are always zero.

Traps the data was built to contain, each of which the service must handle visibly:

| Record(s) | Issue | Expected handling |
|---|---|---|
| CRM-1008 | `meeting_date` is `03-15/2025` | parse with a second pattern, flag `malformed_date` |
| CRM-1007 | `meeting_time` null | start is null, flag `missing_time`, matched only by the time-less rule |
| CRM-1010 | `notes` is `""` | treat as missing, flag `empty_string` |
| CRM-1006/1009/1013/1019 | client null (internal meetings) | participants = owner only |
| CRM-1017 | client_name `Multiple` | treat as no single client, flag `placeholder_client` |
| CRM-1005 | `Kevin O'Brien` | strip non-letters when deriving email |
| CRM-1009 | status Cancelled, note "rescheduled to 3/26" | stays a meeting, conflict with calendar `confirmed` |
| CRM-1008 / CAL-A9 | Saturday meeting | flag `weekend` |
| CAL-A4 | `start_time` ends in `Z` | true UTC, converts to 15:00 local; CRM-1004 says 14:00 |
| CAL-A11 | `end_time` lacks seconds, attendees `[]`, null location and description | flag each; no participants |
| CAL-A16 | attendee `raj.patel[at]atlasvc.com` | repair for matching, flag `malformed_email`, keep raw |
| CAL-A20 | attendee `external-guests` | flag `placeholder_attendee`, excluded from participant set |
| CAL-A5 / CAL-A6 | same organizer, same client, 30 min apart, attendees overlap | same-source duplicate proposal, not collapsed |
| CAL-A3 / CAL-A18 / CAL-A19 | recurring internal syncs | not duplicates; calendar-only singletons |
| CRM-1013 / CAL-A14 | owner Sarah, organizer Priya, Sarah is an attendee | matched by participant containment |
| CRM-1016 / CAL-A17 | 13:00 vs 15:00 | proposal, 120 min gap |
| status vocab | CRM 5 Title Case values, calendar 2 lowercase | shared enum |
| location | same room spelled three ways; "Zoom" vs "In-Person" on CRM-1002/CAL-A2 | kind + raw string; kind conflict is `unresolved` |

Cross-source overlap: 17 real pairs, 3 CRM-only (1003, 1010, 1020), 5 calendar-only (A3, A11, A18, A19, plus A6 as a duplicate of A5).

## 5. Architecture

One process. Pipeline runs at startup and on `POST /sync`, rebuilding the in-memory store wholesale.

```
data/*.json
   │
   ▼
Adapters  (crm_adapter, calendar_adapter)        → list[RawRecord]
   │
   ▼
Normalise (pure, versioned)                      → list[CanonicalRecord] + QualityFlags
   │
   ▼
Reconcile
   ├─ participant resolver  (name→email, company→domain)
   ├─ same-source duplicate detection             → Proposals(kind=duplicate)
   ├─ cascade levels 1..4                         → Matches (auto) + Proposals (levels 2..4)
   └─ merge                                       → Meetings with FieldViews
   │
   ▼
Store (in-memory dicts)  ──  FastAPI routers  ──  static web/ page
```

Package layout (my call):

```
src/eventsync/
  config.py        Settings: tz, windows, auto-merge levels, data paths
  adapters/        crm.py, calendar.py, base.py (SourceAdapter protocol)
  normalize.py     per-field normalisers, NORMALIZER_VERSION
  quality.py       flag rules
  participants.py  resolver: owner email, client email, company domain prefix
  reconcile/
    dedupe.py      within-source proposals
    cascade.py     levels, evidence, match key
    merge.py       FieldView construction, winner rules
  store.py         Store dataclass, rebuild()
  api/             app.py, routers: meetings, proposals, conflicts, quality, sources, stats, sync
web/               index.html, app.js, styles.css (static, served by FastAPI)
tests/             fixtures are the real data files; one test per trap row above
data/              the two inputs
docs/              this spec, the plan, AI collaboration index
notebooks/         eda.ipynb, research notes and report
```

## 6. Canonical model

### RawRecord
`source` (`crm`|`calendar`), `source_id`, `payload` (the JSON object untouched).

### CanonicalRecord
Produced by normalisation. Every field is `Optional`. Raw stays attached.

| Field | Type | CRM source | Calendar source |
|---|---|---|---|
| `title` | str | `subject` | `title` |
| `start` | datetime (naive local) | `meeting_date` + `meeting_time` | `start_time` tz-aware → local → naive |
| `end` | datetime | — | `end_time` same rule |
| `day` | date | from start | from start |
| `owner_email` | str | resolver(`relationship_owner`) | `organizer` |
| `participants` | set[str] | {owner_email, client_email?} | cleaned `attendees` ∪ {organizer} |
| `external_domains` | set[str] | {company_domain_key?} | domains of non-firma attendees |
| `client_name` | str | `client_name` unless placeholder | — |
| `client_company` | str | `client_company` | — |
| `location_raw` | str | `location` | `location` |
| `location_kind` | enum `virtual`/`in_person`/`unknown` | from `meeting_type` then keywords | from keywords |
| `meeting_type` | enum | `meeting_type` | — |
| `status` | enum `scheduled`/`confirmed`/`tentative`/`completed`/`cancelled` | lowercased map | lowercased map |
| `notes` | str | `notes` (empty → None) | `description` |
| `is_recurring` | bool | — | `is_recurring` |
| `created_at` | datetime UTC | `created_at` | `created_at` |
| `flags` | list[QualityFlag] | | |

### QualityFlag
`source`, `source_id`, `field`, `code`, `detail`. Codes: `malformed_date`, `missing_time`, `empty_string`, `placeholder_client`, `placeholder_attendee`, `malformed_email`, `truncated_timestamp`, `utc_timestamp`, `weekend`, `no_participants`, `missing_field`.

### Match
```
kind        auto | proposed | singleton
level       1 | 2 | 3 | 4 | D | null
confidence  high | medium | low
match_key   e.g. "+DAY+START+OWNER+CLIENT"   (Senzing-style: + agreed, - disagreed, ~ missing)
evidence    { same_day, dt_minutes, whole_hour_gap, participants_contained, participants_partial,
              owner_agree, client_agree, title_overlap }
```

### FieldView (one per canonical field on a Meeting)
```
value      served value or null
status     agree | conflict | single_source | missing | unresolved
winner     crm | calendar | null
rule       short text naming the winner rule
crm        { raw, normalized } | null
calendar   { raw, normalized } | null
```
Status rules: both present and equal after normalisation → `agree` (raw may differ, both kept). Both present and different → `conflict` for **comparable** fields, unless the winner rule declines, then `unresolved` with `value` null. Both present and different on a **complementary** field → `differs`. One side only → `single_source`. Neither → `missing`.

Comparable fields (a difference is a disagreement about the meeting): `start`, `end`, `day`, `owner_email`, `client_name`, `client_company`, `status`, `location_kind`, `meeting_type`. Complementary fields (the two systems describe the same thing differently by nature): `title`, `notes`, `participants`, `external_domains`, `location_raw`, `created_at`, `is_recurring`. `conflict_count` counts `conflict` and `unresolved` only; `differs` fields are still shown with both values but do not make a meeting "conflicting". (My call: without this split every merged meeting carries five or six nominal conflicts and the three real disagreements in the data are buried.)

### Meeting
```
meeting_id      "m-" + short hash of sorted source ids
match           Match
sources         { crm: RawRecord|null, calendar: RawRecord|null }
fields          { field_name: FieldView }
flags           [QualityFlag]   (union of both sources)
proposals       [proposal_id]   (open proposals that involve this meeting)
conflict_count  int
```
Singletons are Meetings with one source and every field `single_source` or `missing`.

### Proposal
```
proposal_id   "p-" + hash of the two ids
kind          cross_source | duplicate
level         2 | 3 | 4 | D
left, right   { source, source_id, meeting_id }
reasons       [str]   e.g. "start differs by 60 min (whole-hour gap, possible timezone error)"
evidence      same shape as Match.evidence
preview       cross_source: FieldViews as they would look if merged (winner rules applied)
              duplicate:    { field: { left, right, same: bool } } — plain side-by-side, no winner rules
```
Proposals are read-only in this version. Decisions endpoints are a documented non-goal (section 12).

## 7. Normalisation rules

- Dates: accept `YYYY-MM-DD` and `MM-DD/YYYY`; anything else → start null + `malformed_date`.
- Times: `HH:MM`. Null → `missing_time`.
- Calendar timestamps: parse ISO; if tz-aware convert to `America/New_York` then drop tz and flag `utc_timestamp`; if naive treat as local. Missing seconds → parse anyway, flag `truncated_timestamp`. Seconds dropped everywhere.
- Owner email: `first.last@firma.com` from the display name after lowercasing and stripping non-letters per token. `firma.com` is config (`INTERNAL_DOMAIN`).
- Client key: `first.last` local part derived from `client_name` by the same token rule, skipped when null or placeholder (`Multiple`). It is compared against the **local parts of external attendees** (`kevin.obrien` matches `kevin.obrien@pinnaclegp.com`). No client email is ever fabricated; the CRM `participants` set holds `owner_email` plus the bare client key, and the merged `participants` FieldView serves the calendar list.
- Company domain key: first token of `client_company`, lowercased, letters only (`Meridian Capital` → `meridian`). A calendar external domain matches the key when the domain starts with it (`meridiancap.com`). Verified on every company in the data; documented as a heuristic.
- Attendees: lowercase, trim; `[at]` → `@` with `malformed_email`; tokens without `@` → `placeholder_attendee`, excluded from `participants`.
- Status map: `Scheduled`→scheduled, `Confirmed`/`confirmed`→confirmed, `Tentative`/`tentative`→tentative, `Completed`→completed, `Cancelled`→cancelled.
- Location kind: CRM `meeting_type == Virtual` → virtual; `Internal`/`In-Person` → in_person unless the string contains a virtual keyword (`zoom`, `teams`, `meet`, `webex`, `virtual`); calendar by keywords; null → unknown.
- Empty string → None with `empty_string`.
- `NORMALIZER_VERSION` constant exported in `/stats`.

## 8. Reconciliation cascade

Definitions
- `P(crm)` = owner email plus, when present, the client key.
- **contained** = owner email ∈ participants(cal) AND (no client key on the CRM side, OR client key ∈ external local parts of cal, OR company domain key prefix-matches an external attendee domain).
- **partial** = owner email ∈ participants(cal) but the CRM has a client key and neither client test passes.
- Internal calendar events (no external attendees) can only be contained by a CRM record with no client key.
- `dt` = |start_cal − start_crm| in minutes, None if either start is null.
- Same day is required at every level.
- Windows: `TIGHT_WINDOW_MIN = 10`, `DEDUPE_WINDOW_MIN = 60`, `DEDUPE_JACCARD = 0.5`, `TITLE_OVERLAP = 0.3`. All in config.

Order of operations
1. Same-source duplicate detection over the calendar (and CRM, which yields nothing here): same organizer, same day, `dt ≤ 60`, attendee Jaccard ≥ 0.5 → Proposal kind `duplicate`, level D. Neither record is removed from the pool.
2. **Level 1 pass, per CRM record.** Collect same-day calendar candidates not yet claimed. If one or more satisfy level 1, claim the one with the smallest `dt` (1:1). A CRM record claimed at level 1 generates **no** proposals against other candidates (so CRM-1005 pairs with A5 and does not also propose A6; A6 is covered by the duplicate proposal). A calendar record claimed at level 1 is removed from the pool.
3. **Proposal pass, per (CRM, calendar) pair.** For every unclaimed CRM record and every unclaimed same-day calendar record, evaluate levels 2, 3, 4 in order; the first that fires creates a proposal. Proposals do not claim, so one record may appear in several.
4. `Match.kind` per resulting Meeting: `auto` for level-1 merges, `proposed` for an unmerged record with at least one proposal (cross-source or duplicate), `singleton` for an unmerged record with none. A level-1 merged meeting can still list a duplicate proposal (1005/A5 lists D with A6).

| Level | Rule | Authority | Confidence | In this data |
|---|---|---|---|---|
| 1 | contained and `dt ≤ 10` | auto-merge | high; **medium** when `P(crm)` is owner only (internal or placeholder client) | 14 pairs: 1001/A1, 1002/A2, 1005/A5, 1006/A7, 1008/A9, 1009/A10, 1011/A12, 1012/A13, 1013/A14, 1014/A15, 1015/A16, 1017/A20, 1018/A21, 1019/A22 |
| 2 | contained and `dt > 10` | proposal | medium; reason adds `whole_hour_gap` when `dt % 60 == 0` | 1004/A4 (60, whole hour), 1016/A17 (120, whole hour) |
| 3 | contained and CRM start null | proposal | low | 1007/A8 only (A18 has no external attendee, so it is not contained for a CRM record with a client) |
| 4 | partial and `dt ≤ 10` and title token overlap ≥ 0.3 | proposal | low | none |
| D | duplicate rule above | proposal | — | A5/A6 |
| — | nothing fired | singleton | — | 1003, 1010, 1020, A3, A11, A18, A19 |

Resulting meetings: 14 `auto`, 7 `proposed` (1004, A4, 1016, A17, 1007, A8, A6), 7 `singleton` → 28 meetings from 42 records. Open proposals: 2 at level 2, 1 at level 3, 1 at D.

Auto-merge is permitted for level 1 only (`AUTO_MERGE_LEVELS = {1}` in config). Title overlap: lowercase tokens, letters only, minus a stop list, `|A∩B| / min(|A|,|B|)`.

Match key is built from the evidence: `+DAY`, `+START` if `dt ≤ 10` else `-START`, `+OWNER`/`-OWNER`, `+CLIENT`/`-CLIENT`/`~CLIENT` when absent, `+TITLE` when overlap ≥ 0.3.

## 9. Winner rules (merge)

Applied per field on auto-merged pairs. Each rule is one line of code and its text appears in `FieldView.rule`.

| Field | Winner | Rule text |
|---|---|---|
| start, end, day | calendar | "calendar timestamps are what attendees received" |
| title | crm | "CRM subject is the canonical name; calendar title kept" |
| owner_email | crm | "CRM owns the relationship; organizer kept" |
| client_name, client_company | crm | "CRM is the relationship system of record" |
| external_domains, participants | calendar | "only source with attendee data" |
| status | crm if cancelled or completed else calendar | "CRM carries lifecycle; calendar carries acceptance" |
| location_kind | none when kinds differ → `unresolved`; else calendar | "no basis to prefer a source on kind" |
| location_raw | calendar when kinds agree; else `unresolved` | same |
| notes | crm | "notes are CRM-authored; description kept" |
| meeting_type | crm | single source |
| is_recurring, created_at | calendar for recurring; both kept for created_at as `conflict` when different | "created_at is informational" |

Equality for `agree` uses the normalised value (for example location kind, status enum, minute-resolution time).

## 10. API

All responses JSON. Pagination unnecessary at this size; `limit`/`offset` accepted and documented.

| Method, path | Returns |
|---|---|
| `GET /api/meetings` | list of Meeting summaries: id, `fields.*.value` and `fields.*.status`, `match.kind/level/confidence`, `conflict_count`, flag count. Filters: `source=crm\|calendar\|both`, `has_conflict=true`, `level=1`, `status=`, `owner=`, `from=`, `to=` |
| `GET /api/meetings/{id}` | full Meeting with every FieldView, both raw records, match evidence, flags, proposal ids |
| `GET /api/meetings/{id}/diff` | only FieldViews whose status is not `agree` |
| `GET /api/proposals` | all open proposals with reasons and preview; filter `kind`, `level` |
| `GET /api/proposals/{id}` | one proposal |
| `GET /api/conflicts` | flat rows: meeting_id, field, status, crm value, calendar value, winner, rule |
| `GET /api/quality` | flat quality flags; filter `source`, `code` |
| `GET /api/unmatched` | singletons grouped by source, each with best rejected candidate (highest level reached, its reasons) |
| `GET /api/sources/{src}/{id}` | raw record plus the meeting_id it landed in |
| `GET /api/stats` | counts by match kind/level, by field status, by flag code, source coverage, config (tz, windows, auto-merge levels), `NORMALIZER_VERSION`, last sync time |
| `POST /api/sync` | rerun pipeline, return stats |
| `GET /healthz` | `{"ok": true}` |
| `GET /` | the static page |

Error shape: `{"error": {"code", "message"}}` with 404 for unknown ids, 422 for bad filters.

## 11. Frontend

Static HTML + vanilla JS, no build step, served from `web/` by the API. Visual design is not evaluated; clarity is.

Views (tabs):
1. **Meetings** — table: day, start, title, owner, client, kind, status, match badge (level + confidence), conflict count, flag count. Row click opens the detail panel. Filters mirror the API.
2. **Detail panel** — three columns per field: Reconciled value, CRM, Calendar. Row colour by status (agree / conflict / single_source / unresolved / missing). Rule text on hover or inline. Match evidence and match key at the top. Raw JSON for both sources in collapsible blocks.
3. **Proposals** — list of proposals with reasons; click shows the two records side by side with the merge preview. Read-only; a note explains confirm/reject is a documented next step.
4. **Quality** — flat flag table, filterable by code.
5. **Unmatched** — singletons with the best rejected candidate and why.

## 12. Deliberately not built, and how it would be added

Each gets a paragraph in the README.
- **Decisions ledger**: `POST /api/proposals/{id}/confirm|reject` writing `{proposal_id, decision, decided_at, compared_fields_hash}` to `data/decisions.json`, replayed after the cascade. A decision is re-surfaced only when the hash of the compared fields changes (addresses the "stale lock" failure documented in MDM tools).
- **Persistence**: Store is one dataclass behind `rebuild()`; swap for SQLite or Postgres by implementing the same reads.
- **Scheduling**: `POST /sync` is the hook for a cron or webhook.
- **Live adapters**: `SourceAdapter` protocol has `fetch() -> list[RawRecord]`; a live CRM adapter implements it.
- **Auth, tenancy, rate limits**: one line each on the middleware point.
- **Probabilistic scoring**: why a cascade was chosen (explainability, nothing to train on; industry sources agree scores are too coarse to route review).

## 13. Testing

Pytest. Fixtures are the real data files. One test per trap row in section 4, plus: meeting counts (14 auto, 7 proposed, 7 singleton, 28 total) and proposal counts (2 level-2, 1 level-3, 0 level-4, 1 D), FieldView status for CRM-1002/CAL-A2 `location_kind` `unresolved`, `conflict_count` is non-zero on exactly four auto merges: 1 on 1001/A1 (status), 1009/A10 (status) and 1013/A14 (owner), 2 on 1002/A2 (location kind and raw location both `unresolved`), and 0 on the other ten; CRM-1016/CAL-A17 as proposal with `whole_hour_gap`; idempotent sync (two runs produce identical store), every API route returns 200 and validates against the pydantic models. Coverage percentage is not a target.

## 14. Deliverables

- Code as laid out in section 5; `uv run eventsync` starts the API on `http://127.0.0.1:8000` and serves the page. `uv run pytest` runs tests.
- `README.md`: run command first; approach; the trap table with what the service does for each; cascade and winner rules; what was not built and why; time spent split into research, design, build, docs.
- `docs/ai-collaboration/`: index linking this spec, the plan, `notebooks/eda.ipynb`, the research notes and report, and a short narrative of how AI was used.
- No git history is published; the repository is delivered as a folder or zip.

## 15. Left to the builder

- Exact pydantic model layout and router organisation.
- Hashing scheme for ids (any short stable hash).
- Stop-word list for title overlap.
- Page styling and table component choices.
- Logging format (structured JSON lines preferred, not required).
- Test file organisation.
