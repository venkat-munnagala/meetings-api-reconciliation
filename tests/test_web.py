def test_page_has_tabs(client):
    html = client.get("/").text
    for tab in ("tab-meetings", "tab-proposals", "tab-quality", "tab-unmatched"):
        assert f'id="{tab}"' in html


def test_static_assets(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
