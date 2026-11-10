import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

from .conftest import KEY


@pytest.fixture
def anon(client):
    """A client with no credentials, against an API whose key is KEY."""
    return TestClient(app)


def test_health_is_open(anon):
    assert anon.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/threads"),
        ("post", "/threads"),
        ("patch", "/threads/x"),
        ("delete", "/threads/x"),
        ("post", "/threads/x/touch"),
        ("post", "/threads/x/snooze"),
        ("post", "/threads/x/pause"),
        ("post", "/threads/x/resume"),
        ("get", "/nudges"),
        ("post", "/nudges/send"),
    ],
)
def test_no_key_is_401(anon, method, path):
    r = getattr(anon, method)(path)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_wrong_key_is_401(anon):
    r = anon.get("/threads", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_wrong_scheme_is_401(anon):
    r = anon.get("/threads", headers={"Authorization": f"Basic {KEY}"})
    assert r.status_code == 401


def test_right_key_is_allowed(anon):
    r = anon.get("/threads", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 200


def test_empty_key_never_matches(anon, monkeypatch):
    # A blank configured key must not turn "Bearer " (blank token) into a master key.
    monkeypatch.setattr(config, "API_KEY", "")
    r = anon.get("/threads", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_refuses_to_start_without_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    with pytest.raises(RuntimeError, match="ASSAEE_API_KEY"), TestClient(app):
        pass
