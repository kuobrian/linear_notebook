"""Shared fixtures.

By default every test gets its own in-memory SQLite database. To run the whole suite against another
database, for example PostgreSQL, point LOCAL_LINEAR_TEST_DB at it:

    LOCAL_LINEAR_TEST_DB=postgresql://user:pass@localhost:5432/local_linear_test uv run pytest

All tables in that database are dropped and recreated for every test, so its name must contain
"test"; anything else is refused.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from local_linear import models  # noqa: F401  (registers the tables)
from local_linear.db import Base, get_session, init_db, make_engine, normalize_url
from local_linear.main import app

TEST_DB = os.getenv("LOCAL_LINEAR_TEST_DB")
USING_POSTGRES = bool(TEST_DB) and normalize_url(TEST_DB).startswith("postgresql")

if TEST_DB and "test" not in (make_url(normalize_url(TEST_DB)).database or "").lower():
    raise pytest.UsageError(
        "LOCAL_LINEAR_TEST_DB must name a database containing 'test': the tests drop every table in it"
    )


def fresh_engine():
    """A new, empty database: the one in LOCAL_LINEAR_TEST_DB if set, otherwise in-memory SQLite."""
    engine = make_engine(TEST_DB or "sqlite://")
    if TEST_DB:
        Base.metadata.drop_all(engine)
    init_db(engine)
    return engine


@pytest.fixture()
def client():
    engine = fresh_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def team(client):
    r = client.post("/api/teams", json={"key": "eng", "name": "Engineering"})
    assert r.status_code == 201
    return r.json()


def status_id(team, type_):
    return next(s["id"] for s in team["statuses"] if s["type"] == type_)
