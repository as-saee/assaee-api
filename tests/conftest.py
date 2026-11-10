from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.db import Base, get_session
from app.main import app
from app.routes import get_now

START = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)  # Monday 12:00 in Madrid
KEY = "test-key"


class Clock:
    def __init__(self):
        self.now = START

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(clock, monkeypatch):
    """An in-memory API with a fake clock, and a client that already holds the key."""
    monkeypatch.setattr(config, "API_KEY", KEY)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    def session():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_now] = lambda: clock.now
    yield TestClient(app, headers={"Authorization": f"Bearer {KEY}"})
    app.dependency_overrides.clear()
