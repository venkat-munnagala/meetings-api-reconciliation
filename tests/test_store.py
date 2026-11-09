from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from eventsync.store import build_store, stats


def test_store_counts(store):
    kinds = Counter(m.match.kind.value for m in store.meetings.values())
    assert kinds == {"auto": 14, "proposed": 7, "singleton": 7} and len(store.meetings) == 28
    assert Counter(p.level for p in store.proposals.values()) == {2: 2, 3: 1, "D": 1}


def test_every_record_lands_in_exactly_one_meeting(store):
    assert len(store.by_source_id) == 42 and len(store.raw) == 42
    counted = Counter(sid for m in store.meetings.values() for sid in [r.source_id for r in m.sources.values() if r])
    assert set(counted.values()) == {1}


def test_auto_meeting_lists_duplicate_proposal(store):
    m = store.meetings[store.by_source_id[("calendar", "CAL-A5")]]
    assert m.match.kind == "auto" and len(m.proposals) == 1 and store.proposals[m.proposals[0]].kind == "duplicate"
    a6 = store.meetings[store.by_source_id[("calendar", "CAL-A6")]]
    assert a6.match.kind == "proposed" and a6.proposals == m.proposals


def test_proposal_shape(store):
    p = next(p for p in store.proposals.values() if p.left.source_id == "CRM-1004")
    assert p.kind == "cross_source" and p.level == 2 and p.right.source_id == "CAL-A4"
    assert any("whole-hour" in r for r in p.reasons) and p.evidence.dt_minutes == 60
    assert p.preview["start"]["status"] == "conflict"
    d = next(p for p in store.proposals.values() if p.kind == "duplicate")
    assert d.preview["start"]["same"] is False and d.level == "D"


def test_auto_match_fields(store):
    m = store.meetings[store.by_source_id[("crm", "CRM-1013")]]
    assert m.match.level == 1 and m.match.confidence == "medium" and m.match.match_key == "+DAY+START-OWNER~CLIENT+TITLE"
    m2 = store.meetings[store.by_source_id[("crm", "CRM-1001")]]
    assert m2.match.confidence == "high" and m2.match.match_key == "+DAY+START+OWNER+CLIENT+TITLE"


def test_rejected_best_for_unmatched(store):
    assert store.rejected_best[("crm", "CRM-1003")]["other_id"] == "CAL-A7"
    assert store.rejected_best[("crm", "CRM-1010")] is None
    assert store.rejected_best[("crm", "CRM-1004")]["other_id"] == "CAL-A4"


def test_flags_collected(store):
    codes = Counter(f.code for f in store.flags)
    assert codes["malformed_date"] == 1 and codes["utc_timestamp"] == 2 and codes["malformed_email"] == 1


def test_stats_shape(store):
    s = stats(store)
    assert s["meetings_by_kind"] == {"auto": 14, "proposed": 7, "singleton": 7}
    assert s["proposals_by_level"] == {"2": 2, "3": 1, "D": 1}
    assert s["source_coverage"] == {"crm": 20, "calendar": 22, "both": 14}
    assert s["config"]["tight_window_min"] == 10 and s["normalizer_version"] == "1" and "synced_at" in s
    assert s["fields_by_status"]["conflict"] == 3 and s["fields_by_status"]["unresolved"] == 2


def test_sync_is_idempotent(settings):
    a, b = build_store(settings), build_store(settings)
    assert {k: m.model_dump() for k, m in a.meetings.items()} == {k: m.model_dump() for k, m in b.meetings.items()}
    assert set(a.proposals) == set(b.proposals)


def test_missing_file_raises(settings):
    with pytest.raises(FileNotFoundError):
        build_store(replace(settings, data_dir=Path("/nonexistent")))


def test_rejected_best_notes_when_candidate_already_merged(store):
    best = store.rejected_best[("calendar", "CAL-A19")]
    assert best["other_id"] == "CRM-1017" and best["other_merged_with"] == "CAL-A20"
    assert any("already merged" in r for r in best["reasons"])
    assert store.rejected_best[("crm", "CRM-1003")]["other_merged_with"] == "CRM-1006"
    assert store.rejected_best[("crm", "CRM-1004")]["other_merged_with"] is None
