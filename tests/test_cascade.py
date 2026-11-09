from datetime import datetime

from eventsync.config import DEFAULT
from eventsync.models import Evidence, RawRecord
from eventsync.reconcile.cascade import confidence_for, match_key, run_cascade

AUTO = {("CRM-1001", "CAL-A1"), ("CRM-1002", "CAL-A2"), ("CRM-1005", "CAL-A5"), ("CRM-1006", "CAL-A7"),
        ("CRM-1008", "CAL-A9"), ("CRM-1009", "CAL-A10"), ("CRM-1011", "CAL-A12"), ("CRM-1012", "CAL-A13"),
        ("CRM-1013", "CAL-A14"), ("CRM-1014", "CAL-A15"), ("CRM-1015", "CAL-A16"), ("CRM-1017", "CAL-A20"),
        ("CRM-1018", "CAL-A21"), ("CRM-1019", "CAL-A22")}


def test_level_one_pairs(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert {(c.source_id, k.source_id) for c, k, _ in res.auto} == AUTO


def test_proposals(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    props = {(c.source_id, k.source_id): lvl for c, k, lvl, _ in res.proposals}
    assert props == {("CRM-1004", "CAL-A4"): 2, ("CRM-1016", "CAL-A17"): 2, ("CRM-1007", "CAL-A8"): 3}


def test_whole_hour_gap_flagged(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    ev = {(c.source_id, k.source_id): e for c, k, _, e in res.proposals}
    assert ev[("CRM-1004", "CAL-A4")].dt_minutes == 60 and ev[("CRM-1004", "CAL-A4")].whole_hour_gap
    assert ev[("CRM-1016", "CAL-A17")].dt_minutes == 120 and ev[("CRM-1016", "CAL-A17")].whole_hour_gap
    assert ev[("CRM-1007", "CAL-A8")].dt_minutes is None


def test_claimed_record_generates_no_proposals(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert not any(c.source_id == "CRM-1005" for c, *_ in res.proposals)


def test_unmatched(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    assert {r.source_id for r in res.unmatched} == {
        "CRM-1003", "CRM-1004", "CRM-1007", "CRM-1010", "CRM-1016", "CRM-1020",
        "CAL-A3", "CAL-A4", "CAL-A6", "CAL-A8", "CAL-A11", "CAL-A17", "CAL-A18", "CAL-A19"}


def test_one_calendar_record_claimed_once(canon, settings):
    dup = canon["CRM-1001"].model_copy(update={
        "start": datetime(2025, 3, 10, 14, 5),
        "raw": RawRecord(source="crm", source_id="CRM-9999", payload={})})
    res = run_cascade(list(canon.values()) + [dup], settings)
    claimed = [c.source_id for c, k, _ in res.auto if k.source_id == "CAL-A1"]
    assert claimed == ["CRM-1001"]
    # A1 is claimed; the proposal pass only evaluates levels 2-4, and dt=5 fits none of them
    assert not any(c.source_id == "CRM-9999" for c, *_ in res.proposals)
    assert "CRM-9999" in {r.source_id for r in res.unmatched}


def test_auto_confidence(canon, settings):
    res = run_cascade(list(canon.values()), settings)
    conf = {c.source_id: confidence_for(1, c) for c, *_ in res.auto}
    assert conf["CRM-1001"] == "high" and conf["CRM-1006"] == "medium" and conf["CRM-1017"] == "medium"


def test_match_key():
    ev = Evidence(same_day=True, dt_minutes=0, whole_hour_gap=False, participants_contained=True,
                  participants_partial=False, owner_agree=True, client_agree=True, title_overlap=0.0)
    assert match_key(ev, DEFAULT) == "+DAY+START+OWNER+CLIENT"
    ev2 = ev.model_copy(update={"dt_minutes": 60, "owner_agree": False, "client_agree": None, "title_overlap": 0.5})
    assert match_key(ev2, DEFAULT) == "+DAY-START-OWNER~CLIENT+TITLE"
    ev3 = ev.model_copy(update={"dt_minutes": None})
    assert match_key(ev3, DEFAULT) == "+DAY~START+OWNER+CLIENT"


def test_closest_candidate_wins_regardless_of_id_order(canon, settings):
    # CRM-0999 sorts BEFORE CRM-1001 but is 5 minutes off; CRM-1001 (dt 0) must still claim CAL-A1
    dup = canon["CRM-1001"].model_copy(update={
        "start": datetime(2025, 3, 10, 14, 5),
        "raw": RawRecord(source="crm", source_id="CRM-0999", payload={})})
    res = run_cascade(list(canon.values()) + [dup], settings)
    claimed = [c.source_id for c, k, _ in res.auto if k.source_id == "CAL-A1"]
    assert claimed == ["CRM-1001"]
    assert "CRM-0999" in {r.source_id for r in res.unmatched}
