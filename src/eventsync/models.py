"""Shared data model for the pipeline and the API.

Raw payloads are kept verbatim on every record and every meeting; normalised
values live beside them, never instead of them.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["crm", "calendar"]
Level = int | Literal["D"]


class Status(str, Enum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    tentative = "tentative"
    completed = "completed"
    cancelled = "cancelled"


class LocationKind(str, Enum):
    virtual = "virtual"
    in_person = "in_person"
    unknown = "unknown"


class FieldStatus(str, Enum):
    agree = "agree"
    conflict = "conflict"
    differs = "differs"
    single_source = "single_source"
    missing = "missing"
    unresolved = "unresolved"


class MatchKind(str, Enum):
    auto = "auto"
    proposed = "proposed"
    singleton = "singleton"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class RawRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Source
    source_id: str
    payload: dict[str, Any]


class QualityFlag(BaseModel):
    source: Source
    source_id: str
    field: str
    code: str
    detail: str


class CanonicalRecord(BaseModel):
    """One record from either source after normalisation. Every field is optional."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw: RawRecord
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    day: date | None = None
    owner_email: str | None = None
    client_key: str | None = None
    participants: set[str] = Field(default_factory=set)
    external_domains: set[str] = Field(default_factory=set)
    client_name: str | None = None
    client_company: str | None = None
    location_raw: str | None = None
    location_kind: LocationKind | None = None
    meeting_type: str | None = None
    status: Status | None = None
    notes: str | None = None
    is_recurring: bool | None = None
    created_at: datetime | None = None
    flags: list[QualityFlag] = Field(default_factory=list)

    @property
    def source(self) -> Source:
        return self.raw.source

    @property
    def source_id(self) -> str:
        return self.raw.source_id


class Evidence(BaseModel):
    same_day: bool
    dt_minutes: int | None
    whole_hour_gap: bool
    participants_contained: bool
    participants_partial: bool
    owner_agree: bool
    client_agree: bool | None
    title_overlap: float


class Match(BaseModel):
    kind: MatchKind
    level: Level | None = None
    confidence: Confidence | None = None
    match_key: str | None = None
    evidence: Evidence | None = None


class SideValue(BaseModel):
    raw: Any
    normalized: Any


class FieldView(BaseModel):
    value: Any
    status: FieldStatus
    winner: Source | None = None
    rule: str | None = None
    crm: SideValue | None = None
    calendar: SideValue | None = None


class Meeting(BaseModel):
    meeting_id: str
    match: Match
    sources: dict[Source, RawRecord | None]
    fields: dict[str, FieldView]
    flags: list[QualityFlag] = Field(default_factory=list)
    proposals: list[str] = Field(default_factory=list)
    conflict_count: int = 0


class ProposalSide(BaseModel):
    source: Source
    source_id: str
    meeting_id: str


class Proposal(BaseModel):
    proposal_id: str
    kind: Literal["cross_source", "duplicate"]
    level: Level
    left: ProposalSide
    right: ProposalSide
    reasons: list[str]
    evidence: Evidence | None = None
    preview: dict[str, Any] = Field(default_factory=dict)
