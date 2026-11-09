"""Turn raw source records into CanonicalRecords.

Every helper returns the parsed value together with the flags it raised, so a
value is never coerced silently. Participant fields are filled by
``eventsync.participants`` (called at the end of each normaliser).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from eventsync import quality as q
from eventsync.config import Settings
from eventsync.models import CanonicalRecord, LocationKind, QualityFlag, RawRecord, Status

NORMALIZER_VERSION = "1"

VIRTUAL_KEYWORDS = ("zoom", "teams", "meet", "webex", "virtual")
PLACEHOLDER_CLIENTS = {"multiple", "various", "tbd", "n/a"}
DATE_PATTERNS = ("%Y-%m-%d", "%m-%d/%Y")
STATUS_MAP = {
    "scheduled": Status.scheduled,
    "confirmed": Status.confirmed,
    "tentative": Status.tentative,
    "completed": Status.completed,
    "cancelled": Status.cancelled,
    "canceled": Status.cancelled,
}
_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
_TIME_NO_SECONDS_RE = re.compile(r"T\d{2}:\d{2}(?![:\d])")


# --- field helpers -----------------------------------------------------------

def parse_crm_date(text: str | None, rec: RawRecord | None = None) -> tuple[date | None, QualityFlag | None]:
    rec = rec or RawRecord(source="crm", source_id="?", payload={})
    if text is None:
        return None, q.flag(rec, "meeting_date", q.MISSING_FIELD, "meeting_date is null")
    for i, pattern in enumerate(DATE_PATTERNS):
        try:
            d = datetime.strptime(text.strip(), pattern).date()
        except ValueError:
            continue
        if i > 0:
            return d, q.flag(rec, "meeting_date", q.MALFORMED_DATE, f"{text!r} parsed with fallback pattern {pattern}")
        return d, None
    return None, q.flag(rec, "meeting_date", q.MALFORMED_DATE, f"{text!r} matches no accepted pattern")


def parse_hhmm(text: str | None, rec: RawRecord) -> tuple[time | None, QualityFlag | None]:
    if text is None or text == "":
        return None, q.flag(rec, "meeting_time", q.MISSING_TIME, "meeting_time is null")
    try:
        return datetime.strptime(text.strip(), "%H:%M").time(), None
    except ValueError:
        return None, q.flag(rec, "meeting_time", q.MISSING_TIME, f"{text!r} is not HH:MM")


def parse_calendar_ts(
    text: str | None, tz: str, rec: RawRecord | None = None, field: str = "start_time"
) -> tuple[datetime | None, list[QualityFlag]]:
    rec = rec or RawRecord(source="calendar", source_id="?", payload={})
    if text is None or text == "":
        return None, [q.flag(rec, field, q.MISSING_FIELD, f"{field} is null")]
    flags: list[QualityFlag] = []
    s = text.strip()
    if _TIME_NO_SECONDS_RE.search(s):
        s = _TIME_NO_SECONDS_RE.sub(lambda m: m.group(0) + ":00", s, count=1)
        flags.append(q.flag(rec, field, q.TRUNCATED_TIMESTAMP, f"{text!r} has no seconds; assumed :00"))
    s = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None, flags + [q.flag(rec, field, q.MALFORMED_DATE, f"{text!r} is not ISO 8601")]
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
        flags.append(q.flag(rec, field, q.UTC_TIMESTAMP, f"{text!r} carries an offset; converted to {tz}"))
    return dt.replace(second=0, microsecond=0), flags


def map_status(text: str | None) -> Status | None:
    if text is None:
        return None
    return STATUS_MAP.get(text.strip().lower())


def location_kind(location: str | None, meeting_type: str | None) -> LocationKind:
    loc = (location or "").lower()
    if any(k in loc for k in VIRTUAL_KEYWORDS):
        return LocationKind.virtual
    if meeting_type == "Virtual":
        return LocationKind.virtual
    if location:
        return LocationKind.in_person
    if meeting_type in ("In-Person", "Internal"):
        return LocationKind.in_person
    return LocationKind.unknown


def clean_attendee(text: str, rec: RawRecord | None = None) -> tuple[str | None, QualityFlag | None]:
    rec = rec or RawRecord(source="calendar", source_id="?", payload={})
    s = text.strip().lower()
    repaired = s.replace("[at]", "@").replace("(at)", "@").replace(" at ", "@")
    if _EMAIL_RE.match(repaired):
        if repaired != s:
            return repaired, q.flag(rec, "attendees", q.MALFORMED_EMAIL, f"{text!r} repaired to {repaired!r}")
        return repaired, None
    return None, q.flag(rec, "attendees", q.PLACEHOLDER_ATTENDEE, f"{text!r} is not an email; excluded from participants")


def none_if_empty(text: str | None, rec: RawRecord, field: str) -> tuple[str | None, QualityFlag | None]:
    if text is None:
        return None, q.flag(rec, field, q.MISSING_FIELD, f"{field} is null")
    if text.strip() == "":
        return None, q.flag(rec, field, q.EMPTY_STRING, f"{field} is an empty string")
    return text, None


def parse_created_at(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- record normalisers --------------------------------------------------------

def normalise_crm(rec: RawRecord, s: Settings) -> CanonicalRecord:
    p = rec.payload
    flags: list[QualityFlag] = []

    day, f = parse_crm_date(p.get("meeting_date"), rec)
    flags += [f] if f else []
    t, f = parse_hhmm(p.get("meeting_time"), rec)
    flags += [f] if f else []
    start = datetime.combine(day, t) if day and t else None
    if day and day.weekday() >= 5:
        flags.append(q.flag(rec, "meeting_date", q.WEEKEND, f"{day.isoformat()} is a {day.strftime('%A')}"))

    client_name = p.get("client_name")
    if isinstance(client_name, str) and client_name.strip().lower() in PLACEHOLDER_CLIENTS:
        flags.append(q.flag(rec, "client_name", q.PLACEHOLDER_CLIENT, f"{client_name!r} is a placeholder, not a person"))
        client_name = None

    notes, f = none_if_empty(p.get("notes"), rec, "notes")
    flags += [f] if f else []
    location, f = none_if_empty(p.get("location"), rec, "location")
    flags += [f] if f else []

    out = CanonicalRecord(
        raw=rec,
        title=p.get("subject"),
        start=start,
        end=None,
        day=day,
        client_name=client_name,
        client_company=p.get("client_company"),
        location_raw=location,
        location_kind=location_kind(location, p.get("meeting_type")),
        meeting_type=p.get("meeting_type"),
        status=map_status(p.get("status")),
        notes=notes,
        created_at=parse_created_at(p.get("created_at")),
        flags=flags,
    )
    from eventsync.participants import fill_crm_participants  # local import: participants depends on models only

    return fill_crm_participants(out, p.get("relationship_owner"), s)


def normalise_calendar(rec: RawRecord, s: Settings) -> CanonicalRecord:
    p = rec.payload
    flags: list[QualityFlag] = []

    start, fs = parse_calendar_ts(p.get("start_time"), s.local_tz, rec, "start_time")
    flags += fs
    end, fs = parse_calendar_ts(p.get("end_time"), s.local_tz, rec, "end_time")
    flags += fs
    if start and start.weekday() >= 5:
        flags.append(q.flag(rec, "start_time", q.WEEKEND, f"{start.date().isoformat()} is a {start.strftime('%A')}"))

    attendees: list[str] = []
    for a in p.get("attendees") or []:
        email, f = clean_attendee(a, rec)
        flags += [f] if f else []
        if email:
            attendees.append(email)
    if not attendees:
        flags.append(q.flag(rec, "attendees", q.NO_PARTICIPANTS, "no usable attendee emails"))

    description, f = none_if_empty(p.get("description"), rec, "description")
    flags += [f] if f else []
    location, f = none_if_empty(p.get("location"), rec, "location")
    flags += [f] if f else []

    out = CanonicalRecord(
        raw=rec,
        title=p.get("title"),
        start=start,
        end=end,
        day=start.date() if start else None,
        location_raw=location,
        location_kind=location_kind(location, None),
        status=map_status(p.get("status")),
        notes=description,
        is_recurring=p.get("is_recurring"),
        created_at=parse_created_at(p.get("created_at")),
        flags=flags,
    )
    from eventsync.participants import fill_calendar_participants

    return fill_calendar_participants(out, p.get("organizer"), attendees, s)


def normalise_all(crm: list[RawRecord], cal: list[RawRecord], s: Settings) -> list[CanonicalRecord]:
    return [normalise_crm(r, s) for r in crm] + [normalise_calendar(r, s) for r in cal]
