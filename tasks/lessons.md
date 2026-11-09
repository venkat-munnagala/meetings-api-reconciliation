## 2026-11-09 — matching rules must come from fields, not behaviour
- Wrong: treated "day + client" as sufficient identity on the assumption a firm meets a client once per day; let 60–120 min gaps through as "same meeting with time conflict".
- Right: identity = participants + start within a tight window (±10 min). Anything wider is a near-match for human review, never a merge. Duration compares only where both sides have it (CRM has no end time).
- Rule: when a join rule encodes an assumption about how people behave, demote it to a review signal. Show the candidate and the reason it was refused instead of merging.
