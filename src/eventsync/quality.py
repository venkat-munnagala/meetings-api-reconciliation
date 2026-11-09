"""Quality flag codes and a constructor. Flags annotate records; they never change values."""
from __future__ import annotations

from eventsync.models import QualityFlag, RawRecord

MALFORMED_DATE = "malformed_date"
MISSING_TIME = "missing_time"
EMPTY_STRING = "empty_string"
PLACEHOLDER_CLIENT = "placeholder_client"
PLACEHOLDER_ATTENDEE = "placeholder_attendee"
MALFORMED_EMAIL = "malformed_email"
TRUNCATED_TIMESTAMP = "truncated_timestamp"
UTC_TIMESTAMP = "utc_timestamp"
WEEKEND = "weekend"
NO_PARTICIPANTS = "no_participants"
MISSING_FIELD = "missing_field"
MALFORMED_VALUE = "malformed_value"
UNKNOWN_VOCAB = "unknown_vocab"

ALL_CODES = (
    MALFORMED_DATE,
    MISSING_TIME,
    EMPTY_STRING,
    PLACEHOLDER_CLIENT,
    PLACEHOLDER_ATTENDEE,
    MALFORMED_EMAIL,
    TRUNCATED_TIMESTAMP,
    UTC_TIMESTAMP,
    WEEKEND,
    NO_PARTICIPANTS,
    MISSING_FIELD,
    MALFORMED_VALUE,
    UNKNOWN_VOCAB,
)


def flag(rec: RawRecord, field: str, code: str, detail: str) -> QualityFlag:
    return QualityFlag(source=rec.source, source_id=rec.source_id, field=field, code=code, detail=detail)
