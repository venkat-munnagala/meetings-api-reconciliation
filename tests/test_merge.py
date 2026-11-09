from eventsync.models import Match
from eventsync.reconcile.merge import (
    CANONICAL_FIELDS,
    COMPARABLE,
    COMPLEMENTARY,
    build_meeting,
    duplicate_preview,
    meeting_id_for,
    proposal_id_for,
)


def test_field_sets_partition():
    assert COMPARABLE & COMPLEMENTARY == frozenset() and set(CANONICAL_FIELDS) == COMPARABLE | COMPLEMENTARY


def test_status_conflict_and_winner(pair):
    m = pair("CRM-1001", "CAL-A1")
    fv = m.fields["status"]
    assert fv.status == "conflict" and fv.winner == "crm" and fv.value == "completed"
    assert fv.crm.raw == "Completed" and fv.calendar.raw == "confirmed"
    assert "lifecycle" in fv.rule
    assert m.conflict_count == 1


def test_location_kind_unresolved(pair):
    m = pair("CRM-1002", "CAL-A2")
    assert m.fields["location_kind"].status == "unresolved" and m.fields["location_kind"].value is None
    assert m.fields["location_raw"].status == "unresolved" and m.conflict_count == 2
    assert m.fields["location_raw"].crm.raw == "NYC Office - 30th Floor"


def test_owner_conflict(pair):
    m = pair("CRM-1013", "CAL-A14")
    assert m.fields["owner_email"].status == "conflict" and m.fields["owner_email"].value == "sarah.chen@firma.com"
    assert m.conflict_count == 1


def test_complementary_fields_differ_not_conflict(pair):
    m = pair("CRM-1005", "CAL-A5")
    assert m.fields["title"].status == "differs" and m.fields["created_at"].status == "differs"
    assert m.fields["start"].status == "agree" and m.conflict_count == 0
    assert m.fields["title"].value == "Investor Update"            # CRM subject wins as default side
    assert m.fields["participants"].value == sorted(m.fields["participants"].calendar.normalized)


def test_single_source_and_missing(pair):
    m = pair("CRM-1001", "CAL-A1")
    assert m.fields["end"].status == "single_source" and m.fields["end"].winner == "calendar"
    assert m.fields["meeting_type"].status == "single_source" and m.fields["meeting_type"].winner == "crm"
    assert m.fields["is_recurring"].status == "single_source"


def test_location_agree_after_normalisation(pair):
    m = pair("CRM-1001", "CAL-A1")   # "HQ - Conference Room B" vs "Conference Room B": kind agrees, raw differs
    assert m.fields["location_kind"].status == "agree" and m.fields["location_raw"].status == "differs"


def test_singleton_meeting(canon):
    m = build_meeting(canon["CRM-1003"], None, Match(kind="singleton"))
    assert all(fv.status in {"single_source", "missing"} for fv in m.fields.values()) and m.conflict_count == 0
    assert m.sources["calendar"] is None and m.sources["crm"].source_id == "CRM-1003"


def test_flags_union(pair):
    m = pair("CRM-1008", "CAL-A9")
    assert {f.code for f in m.flags} >= {"malformed_date", "weekend"}


def test_meeting_id_stable():
    assert meeting_id_for(["CAL-A1", "CRM-1001"]) == meeting_id_for(["CRM-1001", "CAL-A1"])
    assert meeting_id_for(["CRM-1001"]).startswith("m-") and proposal_id_for("a", "b") == proposal_id_for("b", "a")


def test_duplicate_preview(canon):
    pv = duplicate_preview(canon["CAL-A5"], canon["CAL-A6"])
    assert pv["start"]["same"] is False and pv["owner_email"]["same"] is True
    assert set(pv) == set(CANONICAL_FIELDS)
