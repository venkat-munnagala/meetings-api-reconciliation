import pytest
from fastapi.testclient import TestClient

from eventsync.api.app import create_app
from eventsync.config import DEFAULT


@pytest.fixture(scope="session")
def settings():
    return DEFAULT


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as c:
        yield c


class ANY_FLAG:
    """Compare a QualityFlag on its code only."""

    def __init__(self, code: str) -> None:
        self.code = code

    def __eq__(self, other) -> bool:
        return getattr(other, "code", None) == self.code

    def __repr__(self) -> str:
        return f"ANY_FLAG({self.code!r})"


@pytest.fixture(scope="session")
def crm_raw(settings):
    from eventsync.adapters.crm import CrmFileAdapter

    return {r.source_id: r for r in CrmFileAdapter(settings.data_dir / "crm_events.json").fetch()}


@pytest.fixture(scope="session")
def cal_raw(settings):
    from eventsync.adapters.calendar import CalendarFileAdapter

    return {r.source_id: r for r in CalendarFileAdapter(settings.data_dir / "calendar_events.json").fetch()}


@pytest.fixture(scope="session")
def canon(settings, crm_raw, cal_raw):
    from eventsync.normalize import normalise_all

    recs = normalise_all(list(crm_raw.values()), list(cal_raw.values()), settings)
    return {r.source_id: r for r in recs}


@pytest.fixture(scope="session")
def pair(canon):
    from eventsync.models import Match
    from eventsync.reconcile.merge import build_meeting

    def _pair(c_id: str, e_id: str):
        return build_meeting(canon[c_id], canon[e_id], Match(kind="auto", level=1, confidence="high"))

    return _pair


@pytest.fixture(scope="session")
def store(settings):
    from eventsync.store import build_store

    return build_store(settings)
