def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_default_settings_values():
    from eventsync.config import DEFAULT

    assert DEFAULT.local_tz == "America/New_York"
    assert DEFAULT.tight_window_min == 10 and DEFAULT.dedupe_window_min == 60
    assert DEFAULT.auto_merge_levels == frozenset({1})
