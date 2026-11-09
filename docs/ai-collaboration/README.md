# Design process with AI

The brief encourages AI assistance and asks for transparency about it. This document is that account. It covers what the final solution had to decide, the reasoning that governed each decision, the alternatives that were considered and why they were rejected, and the places where the assignment's scope was deliberately met with a minimal implementation.

The collaboration was a conversation between a human owner and Claude Code. The AI explored the data, proposed designs, wrote the spec and the plan, and implemented under test-first discipline. The human set the principles, rejected three of the AI's early designs, and made every call that changed what the system does. Those rejections are the most useful part of this record, so they are given in full.

---

## 1. What the solution had to decide

Reconciling two exports that share no key breaks into a small number of questions. Each one is a decision the solution had to make and defend.

| Question | What was decided |
|---|---|
| **Identity.** When are two records the same meeting? | The same people, starting at the same time. Participants named by the CRM must all be on the calendar invite, and the start times must be within ±10 minutes. |
| **Authority.** What may merge automatically and what needs a person? | Only full participant agreement plus a tight time window merges. Everything weaker becomes a proposal with its reasons. |
| **Time.** How are two time representations compared? | Both normalised to local minute resolution. Aware timestamps are converted, never trimmed. |
| **People.** How are a CRM name and a calendar email related? | A deterministic name-to-key rule, with a company-to-domain prefix rule as a fallback for the client. |
| **Duplicates.** What about near-identical records inside one source? | Detected and reported as proposals. Never collapsed by the system. |
| **Conflicts.** When the two sources disagree on a field, what is served? | A winner picked by a named rule, with both values and the rule text served alongside. Fields that differ by nature are marked `differs`, not `conflict`. |
| **Provenance.** How does a user know where a value came from? | Every field carries its status, winner, rule, and both sources' raw and normalised values. |
| **Malformed data.** What happens to a bad date, a bad email, an empty string? | Parsed where safe, flagged always, never coerced silently. |
| **State.** Where does the reconciled view live? | In memory, rebuilt from the files on demand. |

---

## 2. Decisions, the governing logic, and what was rejected

Each decision below names the principle that governed it, in priority order, then the alternatives that were considered and why they lost. The priorities themselves came from reading the brief closely: it is explicit that the handling of each data problem is *not* specified, that the README matters as much as the code, and that the frontend must show where data came from and where it conflicts. That reads as a test of judgment and explainability first, and of engineering breadth second.

### 2.1 Identity by participants and a tight time window

**Chosen.** Two records are one meeting when every person the CRM names (owner, and client contact or client firm) appears on the calendar invite, and the starts are within ±10 minutes.

**Governing logic, in priority order.**
1. *No merge may rest on an assumption about human behaviour.* A rule must be provable from the fields in the two records. Anything that needs "people usually..." to be true is a review signal, not an identity rule.
2. *The strongest statement the two schemas allow is a subset test.* The CRM names at most two people; the calendar lists everyone. Equality of participant sets is impossible, containment is exact.
3. *One person can be double-booked; a whole meeting's participants cannot all be in a different meeting at the same time.* So participants plus time is a sound identity, while either alone is not.

**Rejected: day plus client firm as identity.** The AI's first cascade merged on "same day, same client firm" and treated 60 and 120 minute start gaps as "the same meeting with a time conflict". The owner rejected it on the grounds that it assumes a firm meets a client once a day. Two meetings with the same group can sit back to back, an agenda meeting then a stand-up, and a system that merges them corrupts both. The gaps became proposals, not merges.

**Rejected: owner equals organizer as the people test.** The second design matched the CRM relationship owner to the calendar organizer. It failed on a real pair where the owner attended an invite a colleague had sent. The owner's reframing, that the set of people is what cannot be in two places, moved the test to containment against the attendee list and removed the organizer from identity entirely. The organizer is now just an attribute that can conflict.

**Rejected: a wider time window to catch the 60 and 120 minute pairs.** A window wide enough to merge them would merge a genuine back-to-back meeting with the same people. Every timestamp in the data sits on a :00/:30 grid with zero seconds, so ±10 minutes loses nothing real.

### 2.2 A rule cascade, not a probabilistic score

**Chosen.** Ordered levels with explicit rules. Level 1 auto-merges; levels 2 to 4 propose; a duplicate level proposes within a source. Every match carries the level that fired, the evidence, and a compact match key such as `+DAY+START-OWNER~CLIENT+TITLE`.

**Governing logic.**
1. *Explainability is the deliverable.* The brief asks the user to see where data conflicts. A level and an evidence vector answer "why did these merge" directly; a probability does not say whether the time or the people were off.
2. *Predictability by hand.* A reader can work out the outcome of any pair from the rules table. That is also what makes the cascade testable against the data row by row.
3. *There is nothing to train.* Forty-two records cannot calibrate weights, and a weighted sum would be a disguised guess.

**Rejected: weighted similarity score with a threshold.** The AI's initial proposal was a 0.4/0.3/0.3 weighted score over time, text and client domain with a 0.45 cutoff. It worked on this data, but it hides which evidence agreed, and tuning it would have been fitting to 42 rows. The owner asked for the cascade so that the level of match is itself visible.

### 2.3 Take the data at face value

**Chosen.** The one calendar record with a UTC `Z` suffix is converted to local time, landing an hour off its CRM counterpart. The pair is a proposal whose reason names the gap as a whole-hour difference and a likely timezone error. A person decides.

**Governing logic.**
1. *The data is not lying, it is imperfect.* A record that says UTC is treated as UTC. Flag the suspicion, do not act on it.
2. *A rule that rewrites data to make it fit backfires on the next file.* Trimming the `Z` would match this pair and silently misplace every genuinely UTC record in a future export.

**Rejected: treat the `Z` as a mislabelled local time.** Trivial to implement and it would have produced a clean merge. Rejected because it encodes a guess about an upstream bug as a permanent rule. The owner's position was that in such cases the system shows two meetings and asks.

### 2.4 Conflicts versus expected differences

**Chosen.** Fields are split into *comparable* (start, end, day, owner, client, status, location kind, meeting type) and *complementary* (title, notes, participants, raw location, created_at, recurring). Only comparable fields can be conflicts. Complementary differences are shown with both values but marked `differs` and do not count.

**Governing logic.**
1. *The three real disagreements in the data must be visible.* A status conflict, a location-kind conflict and an owner conflict. Without the split, every merged meeting carries five or six nominal conflicts and those three disappear into the noise.
2. *A title phrased differently is not a disagreement about the meeting.* The two systems describe the same event for different audiences.

**Rejected: every difference is a conflict.** The spec's first draft did this. A reviewer reading the spec as a builder pointed out that `has_conflict=true` would then match everything, which defeats the filter the brief implicitly asks for.

### 2.5 Nothing resolved invisibly

**Chosen.** Each field is served as a view: value, status, winner, rule text, CRM raw and normalised, calendar raw and normalised. Where the rules refuse to pick (location kind room versus video call) the status is `unresolved` and the value is null.

**Governing logic.**
1. *A source of truth built on two inputs must preserve both inputs.* Overwriting a value loses the only evidence that a conflict existed.
2. *Winner rules are opinions and must be labelled as such.* "CRM carries lifecycle, calendar carries acceptance" is a judgment; serving it as text lets a reader disagree.

**Rejected: a merged record with one value per field.** The simplest shape and the one a first pass at this problem usually produces. Rejected because it cannot satisfy "see which source each piece of data came from" without a second API call, and because it makes unresolved conflicts impossible to represent.

### 2.6 Proposals are read-only, with a designed path to decisions

**Chosen.** Pairs the cascade would not merge are listed with reasons and a merge preview. Confirming or rejecting them is designed (an append-only decisions file keyed by proposal with a hash of the compared fields, replayed after each sync) but not built.

**Governing logic.**
1. *Scope.* The brief asks for a simple frontend that shows conflicts. Listing proposals with reasons already makes the reasoning visible. A review workflow is a second feature.
2. *Honesty about what is and is not there.* The design is documented so a reader can see the system knows what comes next.

**Rejected: building confirm and reject now.** Cheap to add, but it brings persistence, idempotency on re-sync and stale-decision handling with it, and none of that is asked for.

### 2.7 In memory, one process, one command

**Chosen.** The pipeline is a pure function of the two files and the settings. Startup runs it; `POST /api/sync` runs it again and swaps the store, keeping the old one on failure.

**Governing logic.**
1. *The brief demands a single start command.* Every added service is a startup failure mode.
2. *The inputs are files and the computation is a full recompute.* There is no incremental state to persist.

**Rejected: a database with migrations, a scheduler, a background sync job.** Each is what a production deployment would add and each is described in the README with its insertion point. None changes what a reviewer can learn from this submission.

---

## 3. Where scope was met minimally on purpose

The assignment is evaluated on judgment and clarity, not on operational completeness. The following were implemented at the smallest size that is honest, and each has a real, well-understood implementation that would replace it in production.

| Area | What is here | What a production system has |
|---|---|---|
| Health and monitoring | `GET /healthz` returning `{"ok": true}`; `GET /api/stats` with counts and the active config | Readiness and liveness probes, metrics export, structured request logging, tracing, alerting on sync failure and on review-queue growth |
| Authentication and authorisation | None. Local internal tool | Identity provider integration, role-based access to the review queue, audit of who confirmed what |
| Persistence | In-memory store, rebuilt on sync | A database holding meetings, proposals and decisions, with migrations and backups |
| Ingestion | Two file adapters behind a one-method protocol | Live API clients with pagination, retries, rate limiting, incremental pulls and change detection |
| Scheduling | `POST /api/sync` on demand | A scheduler or event trigger with run history |
| Human review | Read-only proposals with reasons | Confirm and reject endpoints, a persisted decisions ledger, undo, and expiry when compared fields change |
| Participant resolution | Deterministic name-to-key and company-to-domain-prefix rules, isolated in one module | A contact directory lookup or an identity-resolution service |
| Pagination | `limit` and `offset` accepted on list endpoints | Cursor pagination, server-side sorting |
| Frontend | Static HTML and vanilla JavaScript, no build step | A component framework, a design system, accessibility review |
| Testing | 78 tests pinned to the real data files and to the spec's expected counts | Property-based tests on the normaliser, synthetic adversarial datasets, load tests |

Where any of these would plug in is named in the README.

---

## 4. How the work was done

| Stage | Artefact | What it is |
|---|---|---|
| Explore | [`notebooks/eda.ipynb`](../../notebooks/eda.ipynb) | Progressive analysis of both files. Finds every data problem listed in the README. Investigations that found nothing are parked at the bottom with a one-line note each. |
| Design | this document, section 2 | Three rounds of proposal and rejection before anything was written down. |
| Spec | [`docs/superpowers/specs/2026-11-09-event-sync-service-design.md`](../superpowers/specs/2026-11-09-event-sync-service-design.md) | The written design. An independent reviewer with no conversation history read it as a builder would and raised four questions; all four are settled in the document and marked as calls. |
| Plan | [`docs/superpowers/plans/2026-11-09-event-sync-service.md`](../superpowers/plans/2026-11-09-event-sync-service.md) | Eleven test-first tasks with exact signatures and tests pinned to the data. |
| Build | [`tasks/todo.md`](../../tasks/todo.md) | Each task's tests were written and watched fail before the implementation. |
| Review | section 5 below | A second independent reviewer read the finished code against the spec and plan. |
| Corrections | [`tasks/lessons.md`](../../tasks/lessons.md) | Rules written after each rejection so the same mistake is not made twice. |

The spec reviewer found that the cascade's stated counts did not reconcile, that the client-email rule would have fabricated addresses, that treating title differences as conflicts would bury the real ones, and that duplicate proposals had no preview shape. Each was fixed before the plan was written.

## 5. Final code review and what changed

An independent reviewer read the complete implementation against the spec and plan. No critical issues. Four important ones, all fixed with a failing test written first:

- Non-string values in the JSON (an integer date, an object as a status) crashed the pipeline. They now produce a null value and a `malformed_value` flag.
- An unrecognised status such as "On Hold" was mapped to null without a flag, which hid a real disagreement. It now raises `unknown_vocab`.
- When two CRM records both qualified for the same calendar record, the first by id won rather than the closest in time. Claims are now sorted closest-first.
- Date filters on the meetings endpoint accepted any string. They are typed and return 422 on bad input.

Minor findings the reviewer raised and that were deliberately left are listed at the end of [`tasks/todo.md`](../../tasks/todo.md).
