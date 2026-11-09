from eventsync.participants import company_key, domain_matches, is_contained, is_partial, name_key


def test_name_key_strips_non_letters():
    assert name_key("Kevin O'Brien") == "kevin.obrien"
    assert name_key("Multiple") is None and name_key(None) is None


def test_company_key():
    assert company_key("Meridian Capital") == "meridian" and company_key(None) is None


def test_company_key_prefix_matches_every_company(canon):
    for cid, eid in [("CRM-1001", "CAL-A1"), ("CRM-1005", "CAL-A5"), ("CRM-1012", "CAL-A13"), ("CRM-1018", "CAL-A21")]:
        key = company_key(canon[cid].client_company)
        assert any(domain_matches(key, d) for d in canon[eid].external_domains), (cid, eid)


def test_crm_participants_filled(canon):
    c = canon["CRM-1005"]
    assert c.owner_email == "james.wu@firma.com" and c.client_key == "kevin.obrien"
    assert c.participants == {"james.wu@firma.com", "kevin.obrien"} and c.external_domains == {"pinnacle"}


def test_calendar_participants_filled(canon):
    k = canon["CAL-A16"]
    assert "raj.patel@atlasvc.com" in k.participants and k.external_domains == {"atlasvc.com"}
    assert canon["CAL-A20"].external_domains == {"granitepointcap.com", "horizonwp.com", "pinnaclegp.com"}


def test_contained_when_organizer_differs(canon, settings):
    assert is_contained(canon["CRM-1013"], canon["CAL-A14"], settings)


def test_not_contained_internal_event_for_client_record(canon, settings):
    assert not is_contained(canon["CRM-1007"], canon["CAL-A18"], settings)
    assert is_contained(canon["CRM-1007"], canon["CAL-A8"], settings)


def test_partial_only_owner(canon, settings):
    assert is_partial(canon["CRM-1003"], canon["CAL-A7"], settings)
    assert not is_contained(canon["CRM-1003"], canon["CAL-A7"], settings)


def test_owner_absent_is_neither(canon, settings):
    assert not is_contained(canon["CRM-1011"], canon["CAL-A13"], settings)
    assert not is_partial(canon["CRM-1011"], canon["CAL-A13"], settings)


def test_placeholder_client_contained_by_owner_alone(canon, settings):
    # CRM-1017 has client "Multiple" (no client key) but a company; owner presence is enough
    assert is_contained(canon["CRM-1017"], canon["CAL-A20"], settings)
    assert not is_partial(canon["CRM-1017"], canon["CAL-A20"], settings)
