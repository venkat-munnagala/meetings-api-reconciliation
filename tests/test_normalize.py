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
