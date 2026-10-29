import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from local_linear.db import get_session, init_db, make_engine
from local_linear.main import app


@pytest.fixture()
def client():
    engine = make_engine("sqlite://")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def team(client):
    r = client.post("/api/teams", json={"key": "eng", "name": "Engineering"})
    assert r.status_code == 201
    return r.json()


def status_id(team, type_):
    return next(s["id"] for s in team["statuses"] if s["type"] == type_)
