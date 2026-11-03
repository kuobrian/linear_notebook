"""Server start-up and the two command line entry points."""

import sys

import pytest
from conftest import fresh_engine
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import sessionmaker

import local_linear.main as web
from local_linear import mcp_server
from local_linear import models as m


@pytest.fixture()
def own_db(monkeypatch):
    """Point the web app's start-up at a fresh database instead of the real default one."""
    engine = fresh_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(web, "init_db", lambda: None)  # fresh_engine already created the tables
    monkeypatch.setattr(web, "SessionLocal", factory)
    return factory


def test_startup_seeds_an_empty_database_once(own_db, monkeypatch):
    monkeypatch.delenv("LOCAL_LINEAR_SEED", raising=False)
    for _ in range(2):  # a second start must not seed again
        with TestClient(web.app):
            pass
    with own_db() as db:
        assert db.scalar(select(func.count()).select_from(m.Team)) == 1


def test_startup_skips_seed_data_when_disabled(own_db, monkeypatch):
    monkeypatch.setenv("LOCAL_LINEAR_SEED", "0")
    with TestClient(web.app):
        pass
    with own_db() as db:
        assert db.scalar(select(func.count()).select_from(m.Team)) == 0


def test_startup_creates_the_tables_before_seeding(monkeypatch):
    engine = fresh_engine()
    started = []
    monkeypatch.setattr(web, "init_db", lambda: started.append(inspect(engine).get_table_names()))
    monkeypatch.setenv("LOCAL_LINEAR_SEED", "0")
    with TestClient(web.app):
        pass
    assert len(started) == 1 and "issues" in started[0]


def test_web_main_passes_the_arguments_to_uvicorn(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setattr(sys, "argv", ["local-linear"])
    web.main()
    assert seen == {"app": "local_linear.main:app", "host": "127.0.0.1", "port": 8000, "reload": False}
    monkeypatch.setattr(sys, "argv", ["local-linear", "--host", "0.0.0.0", "--port", "9000", "--reload"])
    web.main()
    assert seen["host"] == "0.0.0.0" and seen["port"] == 9000 and seen["reload"] is True


@pytest.fixture()
def mcp_run(monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(mcp_server, "init_db", lambda: calls.setdefault("init", True))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda transport, **kw: calls.update(stdio=transport))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(http=kw))
    monkeypatch.delenv("LOCAL_LINEAR_TOKEN", raising=False)
    return calls


def test_mcp_main_defaults_to_stdio(mcp_run, capsys):
    mcp_server.main([])
    assert mcp_run == {"init": True, "stdio": "stdio"}
    assert capsys.readouterr().err == ""


def test_mcp_main_http_on_loopback_has_no_warning(mcp_run, capsys):
    mcp_server.main(["--transport", "http", "--port", "9999"])
    assert mcp_run["http"]["host"] == "127.0.0.1" and mcp_run["http"]["port"] == 9999
    assert "stdio" not in mcp_run
    assert capsys.readouterr().err == ""


def test_mcp_main_warns_when_exposed_without_a_token(mcp_run, capsys, monkeypatch):
    mcp_server.main(["--transport", "http", "--host", "0.0.0.0"])
    assert "WARNING" in capsys.readouterr().err and mcp_run["http"]["host"] == "0.0.0.0"
    monkeypatch.setenv("LOCAL_LINEAR_TOKEN", "s3cret")
    mcp_server.main(["--transport", "http", "--host", "0.0.0.0"])
    assert capsys.readouterr().err == ""  # a token makes the bind address safe to use
