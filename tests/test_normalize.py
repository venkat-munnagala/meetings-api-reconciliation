from datetime import date, datetime

from conftest import ANY_FLAG

from eventsync.models import LocationKind, Status
from eventsync.normalize import (
    clean_attendee,
    location_kind,
    map_status,
    normalise_calendar,
    normalise_crm,
    parse_calendar_ts,
    parse_crm_date,
)


def codes(rec):
    return {f.code for f in rec.flags}


def test_malformed_date_second_pattern(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1008"], settings)
    assert c.day == date(2025, 3, 15) and c.start == datetime(2025, 3, 15, 12, 0)
    assert codes(c) >= {"malformed_date", "weekend"}


def test_unparseable_date_is_none_with_flag():
    d, f = parse_crm_date("2025/03/15")
    assert d is None and f.code == "malformed_date"


def test_missing_time(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1007"], settings)
    assert c.start is None and c.day == date(2025, 3, 18) and "missing_time" in codes(c)


def test_empty_notes_becomes_none(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1010"], settings)
    assert c.notes is None and "empty_string" in codes(c)


def test_utc_z_converts_to_local(cal_raw, settings):
    c = normalise_calendar(cal_raw["CAL-A4"], settings)
    assert c.start == datetime(2025, 3, 13, 15, 0) and "utc_timestamp" in codes(c)


def test_non_utc_offset_converts_to_local():
    dt, flags = parse_calendar_ts("2025-03-13T19:00:00+05:30", "America/New_York")
    assert dt == datetime(2025, 3, 13, 9, 30) and flags[0].code == "utc_timestamp"


def test_truncated_end_and_empty_attendees(cal_raw, settings):
    c = normalise_calendar(cal_raw["CAL-A11"], settings)
    assert c.end == datetime(2025, 3, 14, 20, 0)
    assert codes(c) >= {"truncated_timestamp", "no_participants", "missing_field"}


def test_status_map():
    assert map_status("Cancelled") == Status.cancelled and map_status("confirmed") == Status.confirmed
    assert map_status(None) is None


def test_location_kind_cases():
    assert location_kind("Zoom", "In-Person") == LocationKind.virtual
    assert location_kind("NYC Office - 30th Floor", "In-Person") == LocationKind.in_person
    assert location_kind(None, "Virtual") == LocationKind.virtual
    assert location_kind(None, None) == LocationKind.unknown


def test_attendee_cleaning():
    assert clean_attendee("raj.patel[at]atlasvc.com") == ("raj.patel@atlasvc.com", ANY_FLAG("malformed_email"))
    assert clean_attendee("external-guests")[0] is None
    assert clean_attendee(" David.Park@MeridianCap.com ") == ("david.park@meridiancap.com", None)


def test_placeholder_client(crm_raw, settings):
    c = normalise_crm(crm_raw["CRM-1017"], settings)
    assert c.client_name is None and "placeholder_client" in codes(c)


def test_seconds_dropped_and_naive_treated_local(cal_raw, settings):
    c = normalise_calendar(cal_raw["CAL-A1"], settings)
    assert c.start == datetime(2025, 3, 10, 14, 0) and c.end == datetime(2025, 3, 10, 15, 30)
    assert c.start.tzinfo is None and "utc_timestamp" not in codes(c)


def test_non_string_values_do_not_crash(settings):
    from eventsync.models import RawRecord

    rec = RawRecord(source="crm", source_id="CRM-X", payload={
        "crm_id": "CRM-X", "subject": 7, "client_name": None, "client_company": None, "relationship_owner": "Sarah Chen",
        "meeting_date": 20250310, "meeting_time": 1400, "meeting_type": "Internal", "location": None,
        "notes": 5, "status": {"x": 1}, "created_at": 12345})
    c = normalise_crm(rec, settings)
    assert c.start is None and c.day is None and c.status is None
    assert codes(c) >= {"malformed_date", "missing_time", "malformed_value"}
    rec2 = RawRecord(source="calendar", source_id="CAL-X", payload={
        "event_id": "CAL-X", "title": "t", "organizer": "sarah.chen@firma.com", "attendees": ["ok@x.com", 42, None],
        "start_time": 1700000000, "end_time": None, "location": None, "description": None, "is_recurring": "yes",
        "status": "confirmed", "created_at": None})
    k = normalise_calendar(rec2, settings)
    assert k.start is None and k.participants == {"ok@x.com", "sarah.chen@firma.com"}
    assert "malformed_value" in codes(k)


def test_unknown_status_vocab_is_flagged(settings):
    from eventsync.models import RawRecord

    rec = RawRecord(source="crm", source_id="CRM-Y", payload={
        "crm_id": "CRM-Y", "subject": "s", "client_name": None, "client_company": None, "relationship_owner": "Sarah Chen",
        "meeting_date": "2025-03-10", "meeting_time": "14:00", "meeting_type": "Internal", "location": None,
        "notes": "n", "status": "On Hold", "created_at": "not-a-date"})
    c = normalise_crm(rec, settings)
    assert c.status is None and c.created_at is None
    flagged = {(f.field, f.code) for f in c.flags}
    assert ("status", "unknown_vocab") in flagged and ("created_at", "malformed_date") in flagged
