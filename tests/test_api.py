def test_meetings_list_and_filters(client):
    assert len(client.get("/api/meetings").json()) == 28
    assert len(client.get("/api/meetings?source=both").json()) == 14
    assert len(client.get("/api/meetings?source=crm").json()) == 6
    assert len(client.get("/api/meetings?source=calendar").json()) == 8
    assert len(client.get("/api/meetings?has_conflict=true").json()) == 4
    assert len(client.get("/api/meetings?level=1").json()) == 14
    assert len(client.get("/api/meetings?owner=james.wu@firma.com&source=both").json()) == 6
    assert len(client.get("/api/meetings?limit=5&offset=25").json()) == 3


def test_meeting_summary_shape(client):
    row = client.get("/api/meetings?source=both&has_conflict=true").json()[0]
    assert set(row) == {"meeting_id", "match", "fields", "conflict_count", "flag_count"}
    assert set(row["match"]) == {"kind", "level", "confidence", "match_key"}
    assert set(row["fields"]["status"]) == {"value", "status"}


def test_bad_filter_422(client):
    r = client.get("/api/meetings?source=outlook")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_meeting_detail_and_diff(client):
    mid = client.get("/api/sources/crm/CRM-1004").json()["meeting_id"]
    d = client.get(f"/api/meetings/{mid}").json()
    assert d["match"]["kind"] == "proposed" and d["sources"]["calendar"] is None and len(d["proposals"]) == 1
    assert d["fields"]["start"]["crm"]["raw"] == {"meeting_date": "2025-03-13", "meeting_time": "14:00"}
    r = client.get("/api/meetings/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    mid1 = client.get("/api/sources/crm/CRM-1001").json()["meeting_id"]
    diff = client.get(f"/api/meetings/{mid1}/diff").json()
    assert "status" in diff and "start" not in diff and "title" in diff


def test_sources_endpoint(client):
    r = client.get("/api/sources/calendar/CAL-A4").json()
    assert r["record"]["payload"]["start_time"] == "2025-03-13T19:00:00Z" and r["meeting_id"]
    assert client.get("/api/sources/calendar/CAL-A99").status_code == 404
    assert client.get("/api/sources/outlook/CAL-A4").status_code == 422


def test_proposals(client):
    ps = client.get("/api/proposals").json()
    assert len(ps) == 4 and len(client.get("/api/proposals?kind=duplicate").json()) == 1
    assert len(client.get("/api/proposals?level=2").json()) == 2
    pid = ps[0]["proposal_id"]
    assert client.get(f"/api/proposals/{pid}").json()["proposal_id"] == pid
    assert client.get("/api/proposals/p-nope").status_code == 404


def test_conflicts_quality_unmatched(client):
    rows = client.get("/api/conflicts").json()
    assert len(rows) == 5 and set(rows[0]) == {"meeting_id", "field", "status", "crm", "calendar", "winner", "rule"}
    assert any(f["code"] == "malformed_email" for f in client.get("/api/quality").json())
    assert len(client.get("/api/quality?code=utc_timestamp").json()) == 2
    u = client.get("/api/unmatched").json()
    assert {x["source_id"] for x in u["crm"]} == {"CRM-1003", "CRM-1004", "CRM-1007", "CRM-1010", "CRM-1016", "CRM-1020"}
    assert next(x for x in u["crm"] if x["source_id"] == "CRM-1003")["best_candidate"]["other_id"] == "CAL-A7"


def test_stats(client):
    s = client.get("/api/stats").json()
    assert s["meetings_by_kind"] == {"auto": 14, "proposed": 7, "singleton": 7} and s["config"]["tight_window_min"] == 10


def test_sync_and_failure_keeps_store(client, monkeypatch):
    assert client.post("/api/sync").status_code == 200
    import eventsync.api.routes as routes

    def boom(s):
        raise FileNotFoundError("x")

    monkeypatch.setattr(routes, "build_store", boom)
    r = client.post("/api/sync")
    assert r.status_code == 500 and r.json()["error"]["code"] == "sync_failed"
    assert len(client.get("/api/meetings").json()) == 28


def test_root_serves_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_date_filters_validated_and_applied(client):
    assert client.get("/api/meetings?from=notadate").status_code == 422
    assert client.get("/api/meetings?from=03/13/2025").status_code == 422
    rows = client.get("/api/meetings?from=2025-03-20&to=2025-03-21").json()
    assert {r["fields"]["day"]["value"] for r in rows} == {"2025-03-20", "2025-03-21"}
