"""Same-source duplicate detection. Pairs are reported, never collapsed."""
from __future__ import annotations

from itertools import combinations

from eventsync.config import Settings
from eventsync.models import CanonicalRecord

DuplicatePair = tuple[CanonicalRecord, CanonicalRecord, float, int]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def minutes_between(a, b) -> int | None:
    if a is None or b is None:
        return None
    return int(abs((a - b).total_seconds()) // 60)


def find_duplicates(records: list[CanonicalRecord], s: Settings) -> list[DuplicatePair]:
    out: list[DuplicatePair] = []
    for source in ("crm", "calendar"):
        rs = sorted((r for r in records if r.source == source), key=lambda r: r.source_id)
        for a, b in combinations(rs, 2):
            if a.owner_email is None or a.owner_email != b.owner_email or a.day is None or a.day != b.day:
                continue
            dt = minutes_between(a.start, b.start)
            if dt is None or dt > s.dedupe_window_min:
                continue
            j = jaccard(a.participants, b.participants)
            if j >= s.dedupe_jaccard:
                out.append((a, b, j, dt))
    return out
