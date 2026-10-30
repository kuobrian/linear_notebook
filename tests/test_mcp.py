import asyncio
import json

import pytest
from mcp.client import Client
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from local_linear import mcp_server
from local_linear import models as m
from local_linear.db import init_db, make_engine
from local_linear.seed import seed


@pytest.fixture()
def factory(monkeypatch):
    engine = make_engine("sqlite://")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)  # team DEMO, users Me/Alex, one project
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)
    return factory


def call(tool, /, **args):
    """Call a tool through a real in-memory MCP client/server session."""

    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def structured(result):
    assert not result.is_error, result.content[0].text
    sc = result.structured_content
    if sc and set(sc) == {"result"}:  # lists come back wrapped under "result"
        return sc["result"]
    return json.loads(result.content[0].text)  # dicts come back as JSON text


def test_tools_are_registered():
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()

    names = {t.name for t in asyncio.run(run()).tools}
    assert {
        "list_teams", "create_team", "create_project", "list_projects", "get_project", "create_issue", "list_issues",
    } <= names


def test_create_project_persists_and_is_visible(factory):
    project = structured(call(
        "create_project", team="demo", name="Billing revamp", summary="New invoices", status="started",
        priority=2, lead="me", start_date="2026-11-01", target_date="2026-12-31",
    ))
    assert project["name"] == "Billing revamp"
    assert project["lead"]["name"] == "Me"
    assert project["target_date"] == "2026-12-31"
    with Session(factory.kw["bind"]) as db:
        row = db.scalar(select(m.Project).where(m.Project.name == "Billing revamp"))
        assert row is not None and row.status == "started" and row.priority == 2

    listed = structured(call("list_projects", team="DEMO"))
    assert "Billing revamp" in [p["name"] for p in listed]
    fetched = structured(call("get_project", project_id=project["id"]))
    assert fetched["milestones"] == []


def test_create_project_defaults(factory):
    project = structured(call("create_project", team="DEMO", name="Minimal"))
    assert project["status"] == "planned" and project["lead"] is None and project["progress"]["total"] == 0


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({"team": "NOPE", "name": "x"}, "Team 'NOPE' not found"),
        ({"team": "DEMO", "name": "x", "status": "bogus"}, "status must be one of"),
        ({"team": "DEMO", "name": "x", "lead": "Ghost"}, "known users: Me, Alex"),
        ({"team": "DEMO", "name": ""}, "name: String should have at least 1 character"),
        ({"team": "DEMO", "name": "x", "priority": 9}, "priority"),
        ({"team": "DEMO", "name": "x", "target_date": "not-a-date"}, "target_date"),
    ],
)
def test_create_project_errors_are_tool_errors(factory, args, fragment):
    res = call("create_project", **args)
    assert res.is_error
    assert fragment in res.content[0].text
    with Session(factory.kw["bind"]) as db:
        assert db.scalar(select(m.Project).where(m.Project.name == "x")) is None


def test_create_team_then_project_on_empty_workspace(monkeypatch):
    engine = make_engine("sqlite://")
    init_db(engine)  # no seed: no teams yet
    monkeypatch.setattr(mcp_server, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    assert structured(call("list_teams")) == []
    assert "not found" in call("create_project", team="ENG", name="P").content[0].text
    team = structured(call("create_team", key="eng", name="Engineering"))
    assert team["key"] == "ENG" and len(team["statuses"]) == 5
    assert structured(call("create_project", team="ENG", name="P"))["name"] == "P"
    dup = call("create_team", key="ENG", name="Again")
    assert dup.is_error and "already exists" in dup.content[0].text
    bad = call("create_team", key="1bad", name="x")
    assert bad.is_error and "key" in bad.content[0].text


def test_issue_tools(factory):
    pid = structured(call("create_project", team="DEMO", name="P"))["id"]
    issue = structured(call("create_issue", team="DEMO", title="Wire up MCP", project_id=pid, assignee="Alex"))
    assert issue["identifier"] == "DEMO-6" and issue["assignee"]["name"] == "Alex"
    found = structured(call("list_issues", project_id=pid))
    assert [i["identifier"] for i in found] == ["DEMO-6"]
    assert [i["identifier"] for i in structured(call("list_issues", query="wire up"))] == ["DEMO-6"]
    assert call("create_issue", team="DEMO", title="x", project_id=999).is_error
    teams = structured(call("list_teams"))
    assert teams[0]["key"] == "DEMO"
