# Event Sync Service

A small internal service that ingests a sales team's meetings from two upstream systems (a CRM export and a calendar export), works out which records describe the same real-world meeting, and serves one reconciled list through a REST API and a web page. Every served value shows where it came from, whether the two sources agree, and which rule picked the winner when they don't.

The reconciled list is a **source of truth built on both inputs**: it never discards a source value, never hides a disagreement behind a merged value, and never merges two records on an assumption about how people behave. Where the data alone cannot prove two records are one meeting, the service shows both and says why it stopped short.

---

## Run

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). No database, no build step, no network access at runtime.

```bash
uv run eventsync
```

Then open <http://127.0.0.1:8000/>. The API is under `/api/…` and interactive docs are at `/docs`. `PORT` and `HOST` environment variables override the defaults.

```bash
uv run pytest
```

runs the 78 tests. They use the real data files in `data/` as fixtures.

## What you will see

Four tabs.

| Tab | Shows |
|---|---|
| **Meetings** | One row per reconciled meeting (28 from 42 records). Match badge (`auto L1`, `proposed`, `singleton`), confidence, conflict and flag counts. Click a row for the detail panel: every field with its reconciled value, the CRM value, the calendar value, a status colour, and the rule that picked the winner. Raw JSON for both sources is one click away. |
| **Proposals** | Pairs the cascade would not merge on its own, with the reasons and a preview of the merge. Read-only in this version. |
| **Quality** | Every malformed or missing value found during ingestion, by record and field. |
| **Unmatched** | Records with no counterpart, and the closest candidate the cascade rejected with the reason. |

Field status colours: **agree** (same after normalisation), **differs** (both sides have a value, they differ, and that is expected for this field), **conflict** (a real disagreement about the meeting; a winner is picked by rule, both values kept), **unresolved** (a disagreement the rules refuse to settle; no value served), **single source**, **missing**.

---

## Approach

```
data/*.json
   │
   ▼
Adapters  (crm, calendar)               → raw records, kept verbatim
   │
   ▼
Normalise (pure, versioned)             → one canonical shape + quality flags
   │
   ▼
Reconcile
   ├─ participant resolver              name → email key, company → domain key
   ├─ same-source duplicate detection   → proposals, nothing collapsed
   ├─ cascade  (level 1 merges; 2–4 propose)
   └─ merge                             → per-field provenance, winner rules
   │
   ▼
In-memory store  ──  FastAPI  ──  static page
```

The whole pipeline is a pure function of the two files and the settings. `POST /api/sync` runs it again and swaps the store; if it fails the previous store stays.

### The identity principle

A meeting is *these participants, starting at this time*. Two records are the same meeting only when:

1. **everyone the CRM names is on the calendar invite** (the owner, and the client contact or someone from the client's firm), and
2. **the start times are within ±10 minutes** after normalising timezones.

Nothing else merges automatically. In particular, "the firm only meets this client once a day" is not a rule here. Two meetings with the same people can sit back to back, and a rule that assumes otherwise is a silent data-corruption risk. Pairs that agree on participants but not on time, or that cannot be tested because a time is missing, become **proposals** for a person to confirm.

The participant test is deliberately one-directional. The CRM names at most two people; the calendar lists everyone. So the test is *CRM ⊆ calendar*, and the organizer field is not used for identity at all: the CRM owner has to be an **attendee**, which is what lets a meeting Sarah owns but Priya sent the invite for still match.

### Data findings and what the service does with each

The two files were explored first in [`notebooks/eda.ipynb`](notebooks/eda.ipynb). Everything below was found there and is pinned by a test.

| Record(s) | Issue | What the service does |
|---|---|---|
| CRM-1008 | `meeting_date` is `03-15/2025` | parses with a fallback pattern, flags `malformed_date` |
| CRM-1007 | `meeting_time` null | no start; flagged `missing_time`; can only reach the time-less proposal level |
| CRM-1010 | `notes` is `""` | treated as missing, flagged `empty_string` |
| CRM-1006/1009/1013/1019 | client null (internal meetings) | participant set is the owner only; auto-merges get `medium` confidence |
| CRM-1017 | client `Multiple` | flagged `placeholder_client`; treated as no single client |
| CRM-1005 | `Kevin O'Brien` | non-letters stripped when deriving the `kevin.obrien` key |
| CRM-1009 | `Cancelled`, note says "rescheduled to 3/26" | stays a meeting; `status` conflict with the calendar's `confirmed`, CRM wins because it carries lifecycle |
| CRM-1008 / CAL-A9 | Saturday | flagged `weekend` on both |
| CAL-A4 | `start_time` ends in `Z` | taken as true UTC → 15:00 local, flagged `utc_timestamp`. CRM-1004 says 14:00, so the pair is a **proposal** with reason "start differs by 60 min (whole-hour gap, possible timezone error)", not a merge |
| CAL-A11 | `end_time` lacks seconds, attendees `[]`, null location and description | each flagged; no participants, so nothing can match it |
| CAL-A16 | attendee `raj.patel[at]atlasvc.com` | repaired for matching, flagged `malformed_email`, raw kept |
| CAL-A20 | attendee `external-guests` | flagged `placeholder_attendee`, excluded from participants |
| CAL-A5 / CAL-A6 | same organizer and client, 30 min apart, attendees overlap 0.67 | **duplicate proposal**; both records stay |
| CAL-A3 / A18 / A19 | recurring internal syncs | different days, never duplicates; calendar-only singletons |
| CRM-1013 / CAL-A14 | CRM owner Sarah, organizer Priya | auto-merged (Sarah is an attendee); `owner_email` shown as a conflict |
| CRM-1016 / CAL-A17 | 13:00 vs 15:00, same people | **proposal**, 120 min gap, whole-hour |
| CRM-1002 / CAL-A2 | CRM `In-Person` at NYC Office, calendar `Zoom` | `location_kind` and `location_raw` **unresolved**: no basis to prefer either, both shown |
| status vocab | CRM 5 Title Case values, calendar 2 lowercase | mapped to one enum before comparison |
| location strings | same room spelled three ways | compared by kind; raw string is a `differs` field |

### The cascade

Same day is required at every level. **Contained** means every person the CRM names is on the invite. `dt` is the start-time gap in minutes.

| Level | Rule | Authority | Confidence | In this data |
|---|---|---|---|---|
| 1 | contained and `dt ≤ 10` | **auto-merge** | high; medium when the CRM names only the owner | 14 pairs |
| 2 | contained and `dt > 10` | proposal | medium | 1004/A4 (60 min), 1016/A17 (120 min) |
| 3 | contained and the CRM has no time | proposal | low | 1007/A8 |
| 4 | owner on the invite, client not, `dt ≤ 10`, titles overlap | proposal | low | none |
| D | same source, same organizer and day, start within 60 min, attendee Jaccard ≥ 0.5 | proposal | — | A5/A6 |
| — | nothing fires | singleton | — | 3 CRM, 4 calendar |

Level 1 runs first, per CRM record, and claims the closest candidate one-to-one. A record claimed at level 1 generates no proposals. Levels 2–4 then run over every unclaimed same-day pair; proposals never claim, so a record can appear in several.

Result: **14 auto-merged, 7 proposed, 7 singleton = 28 meetings from 42 records**, with 4 open proposals. Every match carries its evidence and a compact match key such as `+DAY+START-OWNER~CLIENT+TITLE` (`+` agreed, `-` disagreed, `~` not testable), so the reason for any merge can be read at a glance.

### Winner rules

Applied per field only when both sources have a value and they differ. The rule text is served on every field so nothing is resolved invisibly.

| Field | Winner | Why |
|---|---|---|
| start, end, day | calendar | invites are what attendees received |
| owner | CRM | CRM owns the relationship; organizer kept |
| client name / company | CRM | relationship system of record |
| status | CRM when `cancelled` or `completed`, else calendar | CRM carries lifecycle, calendar carries acceptance |
| location kind | **none** → `unresolved` | no basis to prefer a source |
| title, notes | CRM shown, calendar kept | complementary: `differs`, not a conflict |
| attendees, raw location, created_at, recurring | calendar shown | only or richer source; `differs` where both exist |

Fields are split into **comparable** (start, end, day, owner, client, status, location kind, meeting type) and **complementary** (title, notes, participants, raw location, created_at, recurring). Only comparable fields can be conflicts. Without that split every merged meeting would carry five or six nominal conflicts and the three real disagreements in this data would be buried.

---

## API

| Method, path | Returns |
|---|---|
| `GET /api/meetings` | summaries; filters `source=crm\|calendar\|both`, `has_conflict`, `level`, `owner`, `status`, `from`, `to`, `limit`, `offset` |
| `GET /api/meetings/{id}` | full meeting: every field with both sides, raw records, match evidence, flags, proposal ids |
| `GET /api/meetings/{id}/diff` | only the fields that are not `agree` |
| `GET /api/proposals` · `/api/proposals/{id}` | open proposals with reasons and merge preview; filters `kind`, `level` |
| `GET /api/conflicts` | one row per conflicting or unresolved field across all meetings |
| `GET /api/quality` | quality flags; filters `source`, `code` |
| `GET /api/unmatched` | singletons by source with the best rejected candidate and why |
| `GET /api/sources/{crm\|calendar}/{id}` | the raw record and the meeting it landed in |
| `GET /api/stats` | counts by kind, level, field status, flag code; source coverage; the active config |
| `POST /api/sync` | re-run the pipeline |
| `GET /healthz` | liveness |

Errors are `{"error": {"code", "message"}}`: unknown id → 404, bad filter value → 422, sync failure → 500 with the previous store intact.

Example, the `start` field of the CRM-1004 / CAL-A4 proposal preview:

```json
"start": {
  "value": "2025-03-13T15:00:00", "status": "conflict", "winner": "calendar",
  "rule": "calendar timestamps are what attendees received",
  "crm":      {"raw": {"meeting_date": "2025-03-13", "meeting_time": "14:00"}, "normalized": "2025-03-13T14:00:00"},
  "calendar": {"raw": "2025-03-13T19:00:00Z", "normalized": "2025-03-13T15:00:00"}
}
```

---

## Key decisions

**A rule cascade, not a probabilistic score.** With 42 records there is nothing to train weights on, and a single confidence number hides the question that matters: *which* evidence agreed and which did not. A score of 0.7 does not tell a reviewer whether the time or the people were off. Named levels with explicit evidence answer that directly, are predictable by hand, and are easy to test.

**±10 minutes.** Every timestamp in both files sits on a :00/:30 grid with zero seconds, so a tight window loses nothing. The two real gaps in the data are 60 and 120 minutes, and the right answer for both is "ask", not "merge". A window wide enough to swallow them would also swallow a genuine back-to-back meeting with the same people, which is exactly the case the design refuses to assume away.

**The UTC stamp is taken at face value.** It would be trivial to trim the `Z` and call it a label error, and the result would match the CRM. But a rule that rewrites data to make it fit is exactly the kind of rule that backfires on the next file. The service converts it correctly, lands 60 minutes off, and raises a proposal whose reason names the whole-hour gap as a likely timezone error. A person decides.

**Proposals are read-only.** Confirm/reject endpoints and a persisted decisions ledger are the obvious next step and are designed below, but they are beyond what a "simple frontend" asks for. Listing proposals with reasons already makes the reconciliation reasoning visible, which is the point.

**In memory, one process, one command.** The sources are files and the pipeline is a pure recompute. A database would add a startup failure mode without changing what a reviewer can learn.

**Thresholds are configuration, echoed by `/api/stats`.** The window, the dedupe window, the Jaccard cutoff, the title-overlap cutoff and which levels may auto-merge are one dataclass. Changing a value and re-syncing is the whole tuning loop.

---

## Not built, and where it would go

- **Decisions ledger.** `POST /api/proposals/{id}/confirm|reject` writing `{proposal_id, decision, decided_at, compared_fields_hash}` to a small JSON file, replayed after each sync. A decision is re-surfaced only when the hash of the compared fields changes, so a rejection made on yesterday's values cannot silently hide a real change in today's.
- **Persistence.** `Store` is one dataclass behind `build_store()`; SQLite or Postgres would implement the same reads.
- **Scheduling.** `POST /api/sync` is the hook for cron or a webhook.
- **Live adapters.** `SourceAdapter` is a one-method protocol (`fetch() -> list[RawRecord]`). The two file adapters are 4 lines each.
- **Auth, tenancy, rate limits.** FastAPI middleware at `create_app()`.
- **A learned matcher.** If the record volume ever justified it, the cascade's evidence objects are already the feature vector.

### Known limitations

- The company-to-domain bridge is a prefix heuristic (`Meridian Capital` → `meridiancap.com`). It holds for every firm in this data and is isolated in `participants.py` so it is the one function to change when it stops holding.
- The CRM names at most two people, so for internal meetings the participant test checks one person and the time window does most of the work. Those merges are marked `medium` confidence for that reason.
- Only the two provided files are supported as inputs.

---

## Project layout

```
src/eventsync/
  config.py            settings, all tunables
  models.py            pydantic models shared by pipeline and API
  adapters/            base protocol + CRM and calendar file adapters
  normalize.py         per-field normalisers, quality flags attached
  quality.py           flag codes
  participants.py      name/company keys, containment test
  reconcile/
    dedupe.py          same-source duplicate proposals
    cascade.py         levels, evidence, match keys
    merge.py           FieldViews and winner rules
  store.py             pipeline → in-memory store, stats
  api/                 FastAPI app, routes, error shape
web/                   index.html, app.js, styles.css (no build step)
tests/                 78 tests; the real data files are the fixtures
data/                  the two inputs
notebooks/             EDA notebook
docs/                  design spec, implementation plan, AI collaboration index
tasks/                 todo and lessons
```

## Time spent

Roughly 8 hours wall-clock across one day, including time where AI agents were running unattended.

| Phase | Hours |
|---|---|
| Reading the brief, exploratory data analysis notebook | 1.5 |
| Architecture and matching-rule design (several rounds of discussion and correction) | 2 |
| Stress-testing the matching rules against failure cases | 1.5 |
| Design spec, reviewer pass, implementation plan | 1 |
| Build (TDD, 11 tasks) and browser check | 1.5 |
| README and documentation | 0.5 |

## AI collaboration

This project was built with Claude Code as a pair. The brainstorming, the EDA, the design spec, the plan, the correction log and the task ledger are all included; see [`docs/ai-collaboration/README.md`](docs/ai-collaboration/README.md) for the design process: what was decided, the reasoning behind each decision, the alternatives that were rejected and why, and where scope was met minimally on purpose.
