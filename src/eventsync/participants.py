"""Participant resolver: bridges CRM names to calendar emails.

The CRM names at most two people (relationship owner, client contact) and a
client company. The calendar lists every attendee by email. This module turns
the CRM side into keys that can be looked for in the calendar side, and defines
the containment test the cascade uses as its identity anchor.

Heuristics live here on purpose so they are visible and replaceable:
- owner/client name -> ``first.last`` key (letters only per token)
- company name -> first token, matched as a prefix of an external email domain
"""
from __future__ import annotations

import re

from eventsync.config import Settings
from eventsync.models import CanonicalRecord

_PLACEHOLDER_NAMES = {"multiple", "various", "tbd", "n/a", "unknown"}


def _letters(token: str) -> str:
    return re.sub(r"[^a-z]", "", token.lower())


def name_key(name: str | None) -> str | None:
    """'Kevin O'Brien' -> 'kevin.obrien'. None for null or placeholder names."""
    if not name or name.strip().lower() in _PLACEHOLDER_NAMES:
        return None
    tokens = [t for t in name.split() if _letters(t)]
    if len(tokens) < 2:
        return _letters(tokens[0]) if tokens else None
    return f"{_letters(tokens[0])}.{_letters(tokens[-1])}"


def company_key(company: str | None) -> str | None:
    """'Meridian Capital' -> 'meridian'."""
    if not company:
        return None
    tokens = [t for t in company.split() if _letters(t)]
    return _letters(tokens[0]) if tokens else None


def domain_matches(key: str | None, domain: str) -> bool:
    return bool(key) and domain.lower().startswith(key)


def local_part(email: str) -> str:
    return email.split("@", 1)[0]


def domain_of(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def is_external(email: str, s: Settings) -> bool:
    return "@" in email and not email.endswith("@" + s.internal_domain)


# --- filling records -----------------------------------------------------------

def fill_crm_participants(rec: CanonicalRecord, owner_name: str | None, s: Settings) -> CanonicalRecord:
    owner_key = name_key(owner_name)
    owner_email = f"{owner_key}@{s.internal_domain}" if owner_key else None
    client_key = name_key(rec.client_name)
    participants = set()
    if owner_email:
        participants.add(owner_email)
    if client_key:
        participants.add(client_key)
    ck = company_key(rec.client_company)
    return rec.model_copy(
        update={
            "owner_email": owner_email,
            "client_key": client_key,
            "participants": participants,
            "external_domains": {ck} if ck else set(),
        }
    )


def fill_calendar_participants(
    rec: CanonicalRecord, organizer: str | None, attendees: list[str], s: Settings
) -> CanonicalRecord:
    org = organizer.strip().lower() if organizer else None
    participants = set(attendees) | ({org} if org else set())
    return rec.model_copy(
        update={
            "owner_email": org,
            "participants": participants,
            "external_domains": {domain_of(a) for a in participants if is_external(a, s)},
        }
    )


# --- identity tests ------------------------------------------------------------

def _client_found(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> bool:
    externals = [a for a in cal.participants if is_external(a, s)]
    if crm.client_key and crm.client_key in {local_part(a) for a in externals}:
        return True
    return any(domain_matches(k, d) for k in crm.external_domains for d in cal.external_domains)


def is_contained(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> bool:
    """Everyone the CRM names is on the calendar invite."""
    if not crm.owner_email or crm.owner_email not in cal.participants:
        return False
    if crm.client_key is None:  # internal meeting or placeholder client: owner is all the CRM names
        return True
    return _client_found(crm, cal, s)


def is_partial(crm: CanonicalRecord, cal: CanonicalRecord, s: Settings) -> bool:
    """Owner is on the invite, but the CRM names a client who cannot be found there."""
    if not crm.owner_email or crm.owner_email not in cal.participants:
        return False
    if crm.client_key is None:
        return False
    return not _client_found(crm, cal, s)
