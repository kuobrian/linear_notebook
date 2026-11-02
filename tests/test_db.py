from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import USING_POSTGRES, fresh_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from local_linear import api
from local_linear import models as m
from local_linear import schemas as s
from local_linear.db import make_engine, normalize_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("postgres://u:p@db:5432/x", "postgresql+psycopg://u:p@db:5432/x"),
        ("postgresql://u:p@db:5432/x", "postgresql+psycopg://u:p@db:5432/x"),
        ("postgresql+psycopg://u:p@db/x", "postgresql+psycopg://u:p@db/x"),  # explicit driver is kept
        ("sqlite:///local_linear.db", "sqlite:///local_linear.db"),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_postgres_url_selects_the_psycopg_driver_without_connecting():
    engine = make_engine("postgresql://user:secret@127.0.0.1:1/never_connected")
    assert engine.dialect.name == "postgresql" and engine.dialect.driver == "psycopg"
    assert engine.pool._pre_ping  # recovers from a restarted database server


def test_sqlite_still_enforces_foreign_keys():
    engine = make_engine("sqlite://")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


@pytest.mark.skipif(not USING_POSTGRES, reason="needs LOCAL_LINEAR_TEST_DB=postgresql://.../..._test")
def test_concurrent_issue_creation_gets_unique_consecutive_numbers():
    """The web app and the MCP server are separate processes writing at once; numbers must not collide."""
    engine = fresh_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        api.create_team(s.TeamIn(key="ENG", name="Engineering"), db)

    def worker():
        for _ in range(5):
            with factory() as db:
                api.create_issue(s.IssueIn(team="ENG", title="x"), db)

    with ThreadPoolExecutor(8) as pool:
        for future in [pool.submit(worker) for _ in range(8)]:
            future.result()  # re-raises e.g. a unique-constraint violation

    with factory() as db:
        assert sorted(db.scalars(select(m.Issue.number))) == list(range(1, 41))
        assert db.scalar(select(m.Team.issue_counter)) == 40
