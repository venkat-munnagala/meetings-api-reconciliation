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
