"""REST routes. Thin: read the store on app.state, filter, shape."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from eventsync.models import Meeting, Status
from eventsync.store import Store, build_store, stats

router = APIRouter(prefix="/api")

SourceFilter = Literal["crm", "calendar", "both"]
Src = Literal["crm", "calendar"]


def _store(request: Request) -> Store:
    return request.app.state.store


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": f"{what} not found"})


def _summary(m: Meeting) -> dict[str, Any]:
    return {
        "meeting_id": m.meeting_id,
        "match": {"kind": m.match.kind, "level": m.match.level, "confidence": m.match.confidence,
                  "match_key": m.match.match_key},
        "fields": {f: {"value": fv.value, "status": fv.status} for f, fv in m.fields.items()},
        "conflict_count": m.conflict_count,
        "flag_count": len(m.flags),
    }


def _sort_key(m: Meeting):
    start = m.fields["start"].value or m.fields["day"].value or "9999"
    return (str(start), m.meeting_id)


@router.get("/meetings")
def list_meetings(
    request: Request,
    source: SourceFilter | None = None,
    has_conflict: bool | None = None,
    level: int | None = None,
    owner: str | None = None,
    status: Status | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    ms = list(_store(request).meetings.values())
    if source == "both":
        ms = [m for m in ms if m.sources["crm"] and m.sources["calendar"]]
    elif source:
        other = "calendar" if source == "crm" else "crm"
        ms = [m for m in ms if m.sources[source] and not m.sources[other]]
    if has_conflict is not None:
        ms = [m for m in ms if (m.conflict_count > 0) == has_conflict]
    if level is not None:
        ms = [m for m in ms if m.match.level == level]
    if owner:
        ms = [m for m in ms if (m.fields["owner_email"].value or "").lower() == owner.lower()]
    if status:
        ms = [m for m in ms if m.fields["status"].value == status.value]
    if from_:
        ms = [m for m in ms if (m.fields["day"].value or "") >= from_]
    if to:
        ms = [m for m in ms if (m.fields["day"].value or "9999") <= to]
    ms.sort(key=_sort_key)
    return [_summary(m) for m in ms[offset : offset + limit]]


@router.get("/meetings/{meeting_id}")
def get_meeting(request: Request, meeting_id: str) -> Meeting:
    m = _store(request).meetings.get(meeting_id)
    if not m:
        raise _not_found(f"meeting {meeting_id}")
    return m


@router.get("/meetings/{meeting_id}/diff")
def get_diff(request: Request, meeting_id: str) -> dict[str, Any]:
    m = _store(request).meetings.get(meeting_id)
    if not m:
        raise _not_found(f"meeting {meeting_id}")
    return {f: fv for f, fv in m.fields.items() if fv.status != "agree"}


@router.get("/proposals")
def list_proposals(
    request: Request, kind: Literal["cross_source", "duplicate"] | None = None, level: str | None = None,
    limit: int = Query(500, ge=1), offset: int = Query(0, ge=0),
) -> list[Any]:
    ps = list(_store(request).proposals.values())
    if kind:
        ps = [p for p in ps if p.kind == kind]
    if level is not None:
        ps = [p for p in ps if str(p.level) == level]
    ps.sort(key=lambda p: (str(p.level), p.left.source_id))
    return ps[offset : offset + limit]


@router.get("/proposals/{proposal_id}")
def get_proposal(request: Request, proposal_id: str) -> Any:
    p = _store(request).proposals.get(proposal_id)
    if not p:
        raise _not_found(f"proposal {proposal_id}")
    return p


@router.get("/conflicts")
def list_conflicts(request: Request, field: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for m in sorted(_store(request).meetings.values(), key=_sort_key):
        for f, fv in m.fields.items():
            if fv.status in ("conflict", "unresolved") and (field is None or f == field):
                rows.append({
                    "meeting_id": m.meeting_id, "field": f, "status": fv.status,
                    "crm": fv.crm.normalized if fv.crm else None,
                    "calendar": fv.calendar.normalized if fv.calendar else None,
                    "winner": fv.winner, "rule": fv.rule,
                })
    return rows


@router.get("/quality")
def list_quality(request: Request, source: Src | None = None, code: str | None = None) -> list[Any]:
    fs = _store(request).flags
    if source:
        fs = [f for f in fs if f.source == source]
    if code:
        fs = [f for f in fs if f.code == code]
    return fs


@router.get("/unmatched")
def list_unmatched(request: Request) -> dict[str, list[dict[str, Any]]]:
    st = _store(request)
    out: dict[str, list[dict[str, Any]]] = {"crm": [], "calendar": []}
    for (src, sid), best in sorted(st.rejected_best.items()):
        out[src].append({"source_id": sid, "meeting_id": st.by_source_id[(src, sid)],
                         "kind": st.meetings[st.by_source_id[(src, sid)]].match.kind, "best_candidate": best})
    return out


@router.get("/sources/{source}/{source_id}")
def get_source_record(request: Request, source: Src, source_id: str) -> dict[str, Any]:
    st = _store(request)
    rec = st.raw.get((source, source_id))
    if not rec:
        raise _not_found(f"{source} record {source_id}")
    return {"record": rec, "meeting_id": st.by_source_id.get((source, source_id))}


@router.get("/stats")
def get_stats(request: Request) -> dict[str, Any]:
    return stats(_store(request))


@router.post("/sync")
def sync(request: Request) -> dict[str, Any]:
    try:
        request.app.state.store = build_store(request.app.state.settings)
    except Exception as e:  # keep the previous store on any failure
        raise HTTPException(status_code=500, detail={"code": "sync_failed", "message": str(e)}) from e
    return stats(request.app.state.store)
