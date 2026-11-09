"""The matching cascade.

Identity = participants contained + start within a tight window. Only level 1
may merge. Everything weaker becomes a proposal for a human. No weights, no
scores: a reader can predict the outcome of any pair by hand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from eventsync.config import Settings
from eventsync.models import CanonicalRecord, Confidence, Evidence
from eventsync.participants import is_contained, is_partial
from eventsync.reconcile.dedupe import minutes_between

STOP_WORDS = {"the", "and", "a", "of", "with", "for", "re", "q1", "review", "meeting", "call", "session", "discussion"}
PROPOSAL_LEVELS = (2, 3, 4)

AutoPair = tuple[CanonicalRecord, CanonicalRecord, Evidence]
ProposalPair = tuple[CanonicalRecord, CanonicalRecord, int, Evidence]


@dataclass
class CascadeResult:
    auto: list[AutoPair] = field(default_factory=list)
    proposals: list[ProposalPair] = field(default_factory=list)
    unmatched: list[CanonicalRecord] = field(default_factory=list)


def _tokens(text: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z ]", " ", (text or "").lower()).split() if t and t not in STOP_WORDS}


def token_overlap(a: str | None, b: str | None) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _client_agree(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> bool | None:
    if crm.client_key is None and not crm.external_domains:
        return None
    from eventsync.participants import _client_found

    return _client_found(crm, cal, s)


def evidence_for(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> Evidence:
    dt = minutes_between(crm.start, cal.start)
    return Evidence(
        same_day=crm.day is not None and crm.day == cal.day,
        dt_minutes=dt,
        whole_hour_gap=dt is not None and dt > 0 and dt % 60 == 0,
        participants_contained=is_contained(crm, cal, s),
        participants_partial=is_partial(crm, cal, s),
        owner_agree=crm.owner_email is not None and crm.owner_email == cal.owner_email,
        client_agree=_client_agree(crm, cal, s),
        title_overlap=token_overlap(crm.title, cal.title),
    )


def level_for(ev: Evidence, s: Settings) -> int | None:
    if not ev.same_day:
        return None
    tight = ev.dt_minutes is not None and ev.dt_minutes <= s.tight_window_min
    if ev.participants_contained and tight:
        return 1
    if ev.participants_contained and ev.dt_minutes is not None:
        return 2
    if ev.participants_contained and ev.dt_minutes is None:
        return 3
    if ev.participants_partial and tight and ev.title_overlap >= s.title_overlap:
        return 4
    return None


def confidence_for(level: int, crm: CanonicalRecord) -> Confidence:
    if level == 1:
        return Confidence.medium if len(crm.participants) <= 1 else Confidence.high
    if level == 2:
        return Confidence.medium
    return Confidence.low


def match_key(ev: Evidence, s: Settings) -> str:
    if ev.dt_minutes is None:
        start = "~START"
    elif ev.dt_minutes <= s.tight_window_min:
        start = "+START"
    else:
        start = "-START"
    owner = "+OWNER" if ev.owner_agree else "-OWNER"
    client = {None: "~CLIENT", True: "+CLIENT", False: "-CLIENT"}[ev.client_agree]
    title = "+TITLE" if ev.title_overlap >= s.title_overlap else ""
    return f"+DAY{start}{owner}{client}{title}"


def reasons_for(ev: Evidence, level: int, s: Settings) -> list[str]:
    out: list[str] = []
    if ev.dt_minutes is None:
        out.append("CRM record has no start time")
    elif ev.dt_minutes > s.tight_window_min:
        msg = f"start differs by {ev.dt_minutes} min"
        if ev.whole_hour_gap:
            msg += " (whole-hour gap, possible timezone error)"
        out.append(msg)
    if ev.participants_contained:
        out.append("all CRM-named participants are on the invite")
    elif ev.participants_partial:
        out.append("owner is on the invite, client is not")
    if not ev.owner_agree:
        out.append("CRM owner is not the calendar organizer")
    if level == 4:
        out.append(f"title overlap {ev.title_overlap:.2f}")
    return out


def run_cascade(records: list[CanonicalRecord], s: Settings) -> CascadeResult:
    crm = sorted((r for r in records if r.source == "crm"), key=lambda r: r.source_id)
    cal = sorted((r for r in records if r.source == "calendar"), key=lambda r: r.source_id)
    claimed_cal: set[str] = set()
    claimed_crm: set[str] = set()
    res = CascadeResult()

    # pass 1: level 1 only, per CRM record, 1:1
    for c in crm:
        hits: list[tuple[CanonicalRecord, Evidence]] = []
        for k in cal:
            if k.source_id in claimed_cal or k.day != c.day:
                continue
            ev = evidence_for(c, k, s)
            if level_for(ev, s) == 1:
                hits.append((k, ev))
        if hits:
            k, ev = min(hits, key=lambda h: (h[1].dt_minutes, h[0].source_id))
            res.auto.append((c, k, ev))
            claimed_cal.add(k.source_id)
            claimed_crm.add(c.source_id)

    # pass 2: levels 2-4, per unclaimed pair, no claiming
    for c in crm:
        if c.source_id in claimed_crm:
            continue
        for k in cal:
            if k.source_id in claimed_cal or k.day != c.day:
                continue
            ev = evidence_for(c, k, s)
            lvl = level_for(ev, s)
            if lvl in PROPOSAL_LEVELS:
                res.proposals.append((c, k, lvl, ev))

    res.unmatched = [r for r in crm + cal if r.source_id not in claimed_crm | claimed_cal]
    return res
