from eventsync.reconcile.dedupe import find_duplicates, jaccard


def test_jaccard():
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3 and jaccard(set(), set()) == 0.0


def test_pinnacle_pair_is_duplicate(canon, settings):
    cal = [c for c in canon.values() if c.source == "calendar"]
    dups = find_duplicates(cal, settings)
    assert [(a.source_id, b.source_id) for a, b, *_ in dups] == [("CAL-A5", "CAL-A6")]
    assert dups[0][2] >= 0.5 and dups[0][3] == 30


def test_recurring_syncs_not_duplicates(canon, settings):
    cal = [c for c in canon.values() if c.source == "calendar"]
    ids = {frozenset((a.source_id, b.source_id)) for a, b, *_ in find_duplicates(cal, settings)}
    assert frozenset(("CAL-A3", "CAL-A18")) not in ids


def test_crm_has_no_duplicates(canon, settings):
    crm = [c for c in canon.values() if c.source == "crm"]
    assert find_duplicates(crm, settings) == []
