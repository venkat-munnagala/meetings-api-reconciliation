"""In-memory store and the pipeline that rebuilds it.

``build_store`` is a pure function of the two input files and the settings.
Sync is "run it again and swap the reference"; there is no incremental state.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from eventsync.adapters.calendar import CalendarFileAdapter
from eventsync.adapters.crm import CrmFileAdapter
from eventsync.config import Settings
from eventsync.models import (
    CanonicalRecord,
    Match,
    MatchKind,
    Meeting,
    Proposal,
    ProposalSide,
    QualityFlag,
    RawRecord,
    Source,
)
from eventsync.normalize import NORMALIZER_VERSION, normalise_all
from eventsync.reconcile.cascade import (
    confidence_for,
    evidence_for,
    level_for,
    match_key,
    reasons_for,
    run_cascade,
)
from eventsync.reconcile.dedupe import find_duplicates, minutes_between
from eventsync.reconcile.merge import build_meeting, duplicate_preview, proposal_id_for

Key = tuple[Source, str]


@dataclass
class Store:
    settings: Settings
    meetings: dict[str, Meeting] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    raw: dict[Key, RawRecord] = field(default_factory=dict)
    by_source_id: dict[Key, str] = field(default_factory=dict)
    flags: list[QualityFlag] = field(default_factory=list)
    rejected_best: dict[Key, dict[str, Any] | None] = field(default_factory=dict)
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    normalizer_version: str = NORMALIZER_VERSION

    def meeting_for(self, source: Source, source_id: str) -> Meeting | None:
        mid = self.by_source_id.get((source, source_id))
        return self.meetings.get(mid) if mid else None


def _key(r: CanonicalRecord) -> Key:
    return (r.source, r.source_id)


def _best_rejected(
    rec: CanonicalRecord, others: list[CanonicalRecord], s: Settings, merged_partner: dict[Key, str | None]
) -> dict[str, Any] | None:
    """For an unmatched record: the same-day candidate from the other source that got furthest."""
    cands = [o for o in others if o.source != rec.source and o.day is not None and o.day == rec.day]
    if not cands:
        return None

    def ranked(o: CanonicalRecord):
        crm, cal = (rec, o) if rec.source == "crm" else (o, rec)
        ev = evidence_for(crm, cal, s)
        lvl = level_for(ev, s)
        dt = ev.dt_minutes if ev.dt_minutes is not None else 10**6
        return (-(lvl or 99) if lvl else -99, dt, o.source_id), ev, lvl

    best = min(cands, key=lambda o: (0 if ranked(o)[2] else 1, ranked(o)[0]))
    _, ev, lvl = ranked(best)
    reasons = reasons_for(ev, lvl or 0, s)
    if not ev.participants_contained and not ev.participants_partial:
        reasons.append("CRM owner is not on the invite")
    partner = merged_partner.get(_key(best))
    if partner:
        reasons.append(f"{best.source_id} is already merged with {partner}")
    return {"other_id": best.source_id, "other_merged_with": partner, "level_reached": lvl,
            "reasons": reasons, "evidence": ev.model_dump()}


def build_store(s: Settings) -> Store:
    crm_raw = CrmFileAdapter(s.data_dir / "crm_events.json").fetch()
    cal_raw = CalendarFileAdapter(s.data_dir / "calendar_events.json").fetch()
    records = normalise_all(crm_raw, cal_raw, s)
    by_id = {_key(r): r for r in records}

    dups = find_duplicates(records, s)
    cascade = run_cascade(records, s)

    store = Store(settings=s)
    store.raw = {(r.source, r.source_id): r for r in crm_raw + cal_raw}
    store.flags = [f for r in records for f in r.flags]

    # auto merges
    for c, k, ev in cascade.auto:
        m = build_meeting(c, k, Match(kind=MatchKind.auto, level=1, confidence=confidence_for(1, c),
                                      match_key=match_key(ev, s), evidence=ev))
        store.meetings[m.meeting_id] = m
        store.by_source_id[_key(c)] = m.meeting_id
        store.by_source_id[_key(k)] = m.meeting_id

    # unmatched records become single-source meetings (kind fixed up below)
    for r in cascade.unmatched:
        m = build_meeting(r if r.source == "crm" else None, r if r.source == "calendar" else None,
                          Match(kind=MatchKind.singleton))
        store.meetings[m.meeting_id] = m
        store.by_source_id[_key(r)] = m.meeting_id

    def side(r: CanonicalRecord) -> ProposalSide:
        return ProposalSide(source=r.source, source_id=r.source_id, meeting_id=store.by_source_id[_key(r)])

    def link(p: Proposal, *recs: CanonicalRecord) -> None:
        store.proposals[p.proposal_id] = p
        for r in recs:
            m = store.meetings[store.by_source_id[_key(r)]]
            if p.proposal_id not in m.proposals:
                m.proposals.append(p.proposal_id)

    # cross-source proposals
    for c, k, lvl, ev in cascade.proposals:
        preview = build_meeting(c, k, Match(kind=MatchKind.proposed, level=lvl, confidence=confidence_for(lvl, c),
                                            match_key=match_key(ev, s), evidence=ev))
        p = Proposal(
            proposal_id=proposal_id_for(c.source_id, k.source_id), kind="cross_source", level=lvl,
            left=side(c), right=side(k), reasons=reasons_for(ev, lvl, s), evidence=ev,
            preview={f: fv.model_dump(mode="json") for f, fv in preview.fields.items()},
        )
        link(p, c, k)

    # same-source duplicate proposals
    for a, b, j, dt in dups:
        p = Proposal(
            proposal_id=proposal_id_for(a.source_id, b.source_id), kind="duplicate", level="D",
            left=side(a), right=side(b),
            reasons=[f"same organizer and day, attendee overlap {j:.2f}, start differs by {dt} min"],
            preview=duplicate_preview(a, b),
        )
        link(p, a, b)

    # a singleton with any proposal is "proposed"
    for m in store.meetings.values():
        if m.match.kind == MatchKind.singleton and m.proposals:
            m.match.kind = MatchKind.proposed

    # best rejected candidate for every unmatched record (noting when that candidate is already merged)
    merged_partner: dict[Key, str | None] = {}
    for c, k, _ in cascade.auto:
        merged_partner[_key(c)] = k.source_id
        merged_partner[_key(k)] = c.source_id
    for r in cascade.unmatched:
        store.rejected_best[_key(r)] = _best_rejected(r, records, s, merged_partner)

    store.synced_at = datetime.now(timezone.utc)
    return store


def stats(store: Store) -> dict[str, Any]:
    both = sum(1 for m in store.meetings.values() if m.sources["crm"] and m.sources["calendar"])
    return {
        "meetings_total": len(store.meetings),
        "meetings_by_kind": dict(Counter(m.match.kind.value for m in store.meetings.values())),
        "proposals_by_level": dict(Counter(str(p.level) for p in store.proposals.values())),
        "fields_by_status": dict(Counter(fv.status.value for m in store.meetings.values() for fv in m.fields.values())),
        "flags_by_code": dict(Counter(f.code for f in store.flags)),
        "source_coverage": {
            "crm": sum(1 for k in store.raw if k[0] == "crm"),
            "calendar": sum(1 for k in store.raw if k[0] == "calendar"),
            "both": both,
        },
        "config": store.settings.as_dict(),
        "normalizer_version": store.normalizer_version,
        "synced_at": store.synced_at.isoformat(),
    }
