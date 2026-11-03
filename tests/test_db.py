from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from conftest import TEST_DB, fresh_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from local_linear import api
from local_linear import models as m
from local_linear import schemas as s
from local_linear.db import init_db, make_engine, normalize_url


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


def race_factory(tmp_path):
    """A database two threads can really write to at once, with team ENG in it."""
    if TEST_DB:
        engine = fresh_engine()
    else:  # a file: the in-memory database shares one connection between threads, so it cannot race
        engine = make_engine(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
        init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        api.create_team(s.TeamIn(key="ENG", name="Engineering"), db)
    return factory


def run_in_threads(count, job):
    with ThreadPoolExecutor(count) as pool:
        for future in [pool.submit(job) for _ in range(count)]:
            future.result()  # re-raises e.g. a unique-constraint violation


def test_concurrent_issue_creation_gets_unique_consecutive_numbers(tmp_path):
    """The web app and the MCP server are separate processes writing at once; numbers must not collide."""
    factory = race_factory(tmp_path)

    def worker():
        for _ in range(5):
            with factory() as db:
                api.create_issue(s.IssueIn(team="ENG", title="x"), db)

    run_in_threads(8, worker)

    with factory() as db:
        assert sorted(db.scalars(select(m.Issue.number))) == list(range(1, 41))
        assert db.scalar(select(m.Team.issue_counter)) == 40


def test_concurrent_cycle_creation_gets_unique_consecutive_numbers(tmp_path):
    factory = race_factory(tmp_path)

    def worker():
        for _ in range(3):
            with factory() as db:
                api.create_cycle(s.CycleIn(team="ENG", starts_at=date(2026, 1, 1), ends_at=date(2026, 1, 14)), db)

    run_in_threads(4, worker)

    with factory() as db:
        assert sorted(db.scalars(select(m.Cycle.number))) == list(range(1, 13))
