"""Build Meetings from matched (or single) records.

Every canonical field becomes a FieldView carrying the served value, a status,
the winner and its rule, and BOTH sources' raw and normalised values. Merging
never discards an input.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import date, datetime
from enum import Enum
from typing import Any

from eventsync.models import (
    CanonicalRecord,
    FieldStatus,
    FieldView,
    LocationKind,
    Match,
    Meeting,
    SideValue,
    Source,
    Status,
)

COMPARABLE = frozenset(
    {"start", "end", "day", "owner_email", "client_name", "client_company", "status", "location_kind", "meeting_type"}
)
COMPLEMENTARY = frozenset(
    {"title", "notes", "participants", "external_domains", "location_raw", "created_at", "is_recurring"}
)
CANONICAL_FIELDS: tuple[str, ...] = (
    "title", "day", "start", "end", "owner_email", "client_name", "client_company", "participants",
    "external_domains", "location_kind", "location_raw", "meeting_type", "status", "notes", "is_recurring", "created_at",
)

# Which raw payload key(s) each canonical field came from, per source. None = source has no such field.
RAW_KEYS: dict[Source, dict[str, tuple[str, ...] | None]] = {
    "crm": {
        "title": ("subject",), "day": ("meeting_date",), "start": ("meeting_date", "meeting_time"), "end": None,
        "owner_email": ("relationship_owner",), "client_name": ("client_name",), "client_company": ("client_company",),
        "participants": ("relationship_owner", "client_name"), "external_domains": ("client_company",),
        "location_kind": ("location", "meeting_type"), "location_raw": ("location",), "meeting_type": ("meeting_type",),
        "status": ("status",), "notes": ("notes",), "is_recurring": None, "created_at": ("created_at",),
    },
    "calendar": {
        "title": ("title",), "day": ("start_time",), "start": ("start_time",), "end": ("end_time",),
        "owner_email": ("organizer",), "client_name": None, "client_company": None,
        "participants": ("attendees",), "external_domains": ("attendees",),
        "location_kind": ("location",), "location_raw": ("location",), "meeting_type": None,
        "status": ("status",), "notes": ("description",), "is_recurring": ("is_recurring",), "created_at": ("created_at",),
    },
}

WinnerRule = Callable[[Any, Any], tuple[Source | None, str]]

_CAL_TIME = "calendar timestamps are what attendees received"
WINNER_RULES: dict[str, WinnerRule] = {
    "start": lambda c, k: ("calendar", _CAL_TIME),
    "end": lambda c, k: ("calendar", _CAL_TIME),
    "day": lambda c, k: ("calendar", _CAL_TIME),
    "owner_email": lambda c, k: ("crm", "CRM owns the relationship; organizer kept"),
    "client_name": lambda c, k: ("crm", "CRM is the relationship system of record"),
    "client_company": lambda c, k: ("crm", "CRM is the relationship system of record"),
    "status": lambda c, k: (
        ("crm", "CRM carries lifecycle; calendar carries acceptance")
        if c in (Status.cancelled, Status.completed)
        else ("calendar", "CRM carries lifecycle; calendar carries acceptance")
    ),
    "location_kind": lambda c, k: (None, "no basis to prefer a source on kind"),
    "meeting_type": lambda c, k: ("crm", "single source"),
}

# Default side shown for complementary fields when both sources have a value.
DEFAULT_SIDE: dict[str, Source] = {
    "title": "crm", "notes": "crm", "participants": "calendar", "external_domains": "calendar",
    "location_raw": "calendar", "created_at": "calendar", "is_recurring": "calendar",
}
_DIFFERS_RULE = "systems describe this differently by nature; {side} shown, both kept"


# --- helpers -------------------------------------------------------------------

def meeting_id_for(ids: Iterable[str]) -> str:
    return "m-" + hashlib.sha1("|".join(sorted(ids)).encode()).hexdigest()[:10]


def proposal_id_for(a: str, b: str) -> str:
    return "p-" + hashlib.sha1("|".join(sorted((a, b))).encode()).hexdigest()[:10]


def _jsonable(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _raw_for(rec: CanonicalRecord | None, field: str) -> Any:
    if rec is None:
        return None
    keys = RAW_KEYS[rec.source].get(field)
    if keys is None:
        return None
    if len(keys) == 1:
        return rec.raw.payload.get(keys[0])
    return {k: rec.raw.payload.get(k) for k in keys}


def _has(rec: CanonicalRecord | None, field: str) -> bool:
    if rec is None or RAW_KEYS[rec.source].get(field) is None:
        return False
    v = getattr(rec, field)
    return v is not None and v != set()


def _side(rec: CanonicalRecord | None, field: str) -> SideValue | None:
    if rec is None or RAW_KEYS[rec.source].get(field) is None:
        return None
    return SideValue(raw=_raw_for(rec, field), normalized=_jsonable(getattr(rec, field)))


def _equal(field: str, c: Any, k: Any) -> bool:
    if isinstance(c, str) and isinstance(k, str):
        return c.strip().casefold() == k.strip().casefold()
    return c == k


# --- field views -----------------------------------------------------------------

def build_fieldview(field: str, crm: CanonicalRecord | None, cal: CanonicalRecord | None) -> FieldView:
    has_c, has_k = _has(crm, field), _has(cal, field)
    side_c, side_k = _side(crm, field), _side(cal, field)
    c = getattr(crm, field) if has_c else None
    k = getattr(cal, field) if has_k else None

    if not has_c and not has_k:
        return FieldView(value=None, status=FieldStatus.missing, crm=side_c, calendar=side_k)
    if has_c != has_k:
        winner: Source = "crm" if has_c else "calendar"
        return FieldView(value=_jsonable(c if has_c else k), status=FieldStatus.single_source, winner=winner,
                         rule="only source with a value", crm=side_c, calendar=side_k)
    if _equal(field, c, k):
        return FieldView(value=_jsonable(k), status=FieldStatus.agree, crm=side_c, calendar=side_k)

    if field == "location_raw" and _kinds_disagree(crm, cal):
        return FieldView(value=None, status=FieldStatus.unresolved, rule="location kind disagrees; no basis to prefer a string",
                         crm=side_c, calendar=side_k)
    if field in COMPLEMENTARY:
        side = DEFAULT_SIDE[field]
        return FieldView(value=_jsonable(c if side == "crm" else k), status=FieldStatus.differs, winner=side,
                         rule=_DIFFERS_RULE.format(side=side), crm=side_c, calendar=side_k)

    winner, rule = WINNER_RULES[field](c, k)
    if winner is None:
        return FieldView(value=None, status=FieldStatus.unresolved, rule=rule, crm=side_c, calendar=side_k)
    return FieldView(value=_jsonable(c if winner == "crm" else k), status=FieldStatus.conflict, winner=winner, rule=rule,
                     crm=side_c, calendar=side_k)


def _kinds_disagree(crm: CanonicalRecord | None, cal: CanonicalRecord | None) -> bool:
    if crm is None or cal is None:
        return False
    kc, kk = crm.location_kind, cal.location_kind
    return kc not in (None, LocationKind.unknown) and kk not in (None, LocationKind.unknown) and kc != kk


def build_fieldviews(crm: CanonicalRecord | None, cal: CanonicalRecord | None) -> dict[str, FieldView]:
    return {f: build_fieldview(f, crm, cal) for f in CANONICAL_FIELDS}


# --- meetings ----------------------------------------------------------------------

def build_meeting(crm: CanonicalRecord | None, cal: CanonicalRecord | None, match: Match) -> Meeting:
    fields = build_fieldviews(crm, cal)
    ids = [r.source_id for r in (crm, cal) if r is not None]
    flags = (crm.flags if crm else []) + (cal.flags if cal else [])
    return Meeting(
        meeting_id=meeting_id_for(ids),
        match=match,
        sources={"crm": crm.raw if crm else None, "calendar": cal.raw if cal else None},
        fields=fields,
        flags=flags,
        conflict_count=sum(fv.status in (FieldStatus.conflict, FieldStatus.unresolved) for fv in fields.values()),
    )


def duplicate_preview(a: CanonicalRecord, b: CanonicalRecord) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in CANONICAL_FIELDS:
        va, vb = getattr(a, f), getattr(b, f)
        out[f] = {"left": _jsonable(va), "right": _jsonable(vb), "same": _equal(f, va, vb)}
    return out
