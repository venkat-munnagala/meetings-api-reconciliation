"""Participant resolver: bridges CRM names to calendar emails.

Task 3 stub: fills owner_email/participants minimally. Task 4 completes the
resolver (name keys, company keys, containment tests).
"""
from __future__ import annotations

from eventsync.config import Settings
from eventsync.models import CanonicalRecord


def fill_crm_participants(rec: CanonicalRecord, owner_name: str | None, s: Settings) -> CanonicalRecord:
    return rec


def fill_calendar_participants(
    rec: CanonicalRecord, organizer: str | None, attendees: list[str], s: Settings
) -> CanonicalRecord:
    return rec
