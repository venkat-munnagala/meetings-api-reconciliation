# AI collaboration

The brief encourages AI assistance and transparency about it. This folder indexes every artefact the collaboration produced, in the order it happened, and records the places where the design changed because of a human correction or a research finding.

## Artefacts

| Stage | Artefact | What it is |
|---|---|---|
| 1. Explore | [`notebooks/eda.ipynb`](../../notebooks/eda.ipynb) | Progressive exploratory analysis of both files. Finds every data trap listed in the README. Investigations that found nothing are parked at the bottom with a one-line note each. |
| 2. Design discussion | this README, section below | The matching rules went through three revisions in conversation before anything was written down. |
| 3. Research | [`notebooks/research_notes/Enterprise dirty record reconciliation/`](../../notebooks/research_notes/Enterprise%20dirty%20record%20reconciliation/) | Five research angles (entity-resolution methods, MDM platforms, calendar↔CRM sync products, provenance and conflict models, financial reconciliation tools), each a cited notes file produced by Antigravity's browser agent reading primary sources. |
| | [`notebooks/reports/Enterprise dirty record reconciliation.md`](../../notebooks/reports/Enterprise%20dirty%20record%20reconciliation.md) | Synthesis of the five, written against the design under discussion: where industry practice agrees, where it pushes back, concrete thresholds, vendor terminology, documented failure modes. |
| 4. Spec | [`docs/superpowers/specs/2026-11-09-event-sync-service-design.md`](../superpowers/specs/2026-11-09-event-sync-service-design.md) | The written design. A fresh reviewer read it as a builder would and raised four questions; all four are settled in the document and marked as calls. |
| 5. Plan | [`docs/superpowers/plans/2026-11-09-event-sync-service.md`](../superpowers/plans/2026-11-09-event-sync-service.md) | Eleven TDD tasks with exact signatures and tests pinned to the data. |
| 6. Build | git history, [`tasks/todo.md`](../../tasks/todo.md) | One commit per task; each task's tests were written first and watched fail. |
| 7. Corrections | [`tasks/lessons.md`](../../tasks/lessons.md) | Rules written after being corrected, so the same mistake is not made twice. |

## How the design changed

**Round 1: day + client as identity.** The first cascade treated "same day and same client firm" as sufficient identity, on the reasoning that a firm does not meet the same client twice in a day. It would have merged the 60-minute and 120-minute pairs as "same meeting with a time conflict".

**Correction: that is a behavioural assumption.** The human pointed out that two meetings with the same group can sit back to back (an agenda meeting, then a standup), and that assumptions about how people behave are the costly kind. Identity moved to *participants plus a tight start window*, and anything wider became a proposal for review rather than a merge. Written up in `tasks/lessons.md`.

**Round 2: owner equality as the participant test.** Matching owner to organizer failed on one real pair (the CRM owner was an attendee of an invite a colleague sent).

**Correction: a team cannot be double-booked identically.** The human's framing: one person can have a scheduling conflict, but the whole set of people in a meeting cannot all be in a different meeting at the same time. The test became *containment*: everyone the CRM names must be on the calendar invite, checked against attendees rather than the organizer. This both fixed the failing pair and removed the organizer from identity altogether.

**Round 3: the UTC stamp.** Trimming the `Z` would have made the pair match. The decision was to take the data at face value, let the pair land 60 minutes apart, and surface it with the reason, because a rule that rewrites data to fit is the kind that backfires.

**What the research changed.** Three things in the spec come directly from the research report: the `differs` status for fields that are complementary by nature (otherwise every merged meeting looks conflicted); the whole-hour-gap reason on proposals (documented calendar-sync failures are almost always exact hours); and the design of the decisions ledger with a compared-fields hash (the "stale lock" failure MDM vendors document). The report also confirmed the two-tier commit/suggest structure is standard practice (BlackLine, Oracle ARCS, Modern Treasury, Reltio, IBM) and that rule-based routing to review is preferred over a single score (Google, Senzing, AWS).

**Builder review of the spec.** A fresh agent that had not seen the conversation read the spec and found that: the cascade counts did not reconcile (16 auto claimed, only 14 possible); the client-email rule would have fabricated addresses; counting title/notes differences as conflicts would bury the real ones; and duplicate proposals had no preview shape. Each is now settled in the spec and tested.

## How the tools were used

- **Claude Code** drove the whole process: EDA notebook generation and execution, the design conversation, spec and plan writing, implementation under TDD with one commit per task, and this documentation.
- **Antigravity** (Google's agent, run headless through its CLI with a browser attached) did the five research angles, opening and reading primary sources and writing cited notes. Its notes were then read by a separate synthesis agent that had the design context.
- Sub-agents with no conversation history were used twice on purpose: to review the spec as a builder would, and to review the finished code at the end. Fresh context is what makes a review worth something.
