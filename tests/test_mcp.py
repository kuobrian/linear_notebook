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
        "list_teams", "create_team", "list_labels", "create_label", "create_project", "update_project",
        "list_projects", "get_project", "create_issue", "update_issue", "get_issue", "list_issues",
        "add_comment", "delete_issue",
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


# ---- issue lifecycle tools (status, labels, update, comment, delete) -------------------------
def test_create_issue_with_status_labels_and_more(factory):
    parent = structured(call("create_issue", team="DEMO", title="parent"))
    issue = structured(call(
        "create_issue", team="DEMO", title="Excel import fails", description="**steps**", status="In Progress",
        priority=2, labels=["bug", "Feature"], estimate=3, due_date="2026-12-31", parent=parent["identifier"],
    ))
    assert issue["status"]["name"] == "In Progress"
    assert sorted(label["name"] for label in issue["labels"]) == ["Bug", "Feature"]  # case-insensitive match
    assert issue["estimate"] == 3 and issue["due_date"] == "2026-12-31"
    assert issue["parent_identifier"] == parent["identifier"]
    assert "<strong>steps</strong>" in issue["description_html"]
    # a status *type* works too, and the default stays Backlog
    assert structured(call("create_issue", team="DEMO", title="t", status="completed"))["status"]["name"] == "Done"
    assert structured(call("create_issue", team="DEMO", title="d"))["status"]["name"] == "Backlog"


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({"status": "Reviewing"}, "valid: Backlog, Todo, In Progress, Done, Canceled"),
        ({"labels": ["Nope"]}, "Unknown label(s): Nope"),
        ({"due_date": "tomorrow"}, "due_date must be an ISO date"),
        ({"parent": "DEMO-999"}, "not found"),
        ({"assignee": "Ghost"}, "known users"),
    ],
)
def test_create_issue_rejects_unknown_values_instead_of_ignoring_them(factory, args, fragment):
    res = call("create_issue", team="DEMO", title="x", **args)
    assert res.is_error and fragment in res.content[0].text
    # the rejected call must not have created a half-configured issue
    assert all(i["title"] != "x" for i in structured(call("list_issues", team="DEMO")))


def test_update_issue(factory):
    structured(call("create_issue", team="DEMO", title="old", labels=["Bug"], assignee="Alex", project_id=1))
    out = structured(call(
        "update_issue", issue="DEMO-6", title="new", status="Done", priority=1, labels=["Feature"],
        estimate=5, due_date="2027-01-01", description="# hi",
    ))
    assert out["title"] == "new" and out["status"]["name"] == "Done" and out["completed_at"]
    assert out["priority"] == 1 and [label["name"] for label in out["labels"]] == ["Feature"]
    assert out["description_html"] == "<h1>hi</h1>\n"
    assert out["assignee"]["name"] == "Alex" and out["project_id"] == 1  # untouched fields are kept

    cleared = structured(call("update_issue", issue="demo-6", assignee="", project_id=0, due_date="", labels=[]))
    assert cleared["assignee"] is None and cleared["project_id"] is None
    assert cleared["due_date"] is None and cleared["labels"] == []
    reopened = structured(call("update_issue", issue="DEMO-6", status="started"))
    assert reopened["status"]["name"] == "In Progress" and reopened["completed_at"] is None


def test_update_issue_errors(factory):
    structured(call("create_issue", team="DEMO", title="t"))
    assert "Nothing to update" in call("update_issue", issue="DEMO-6").content[0].text
    assert "not found" in call("update_issue", issue="DEMO-404", title="x").content[0].text
    bad = call("update_issue", issue="DEMO-6", status="Nope")
    assert bad.is_error and "valid:" in bad.content[0].text
    assert structured(call("get_issue", issue="DEMO-6"))["title"] == "t"  # failed updates change nothing


def test_comment_get_and_delete_issue(factory):
    structured(call("create_issue", team="DEMO", title="doomed"))
    comment = structured(call("add_comment", issue="DEMO-6", body="**hello**", author="Me"))
    assert comment["author"]["name"] == "Me" and "<strong>hello</strong>" in comment["body_html"]
    assert structured(call("get_issue", issue="DEMO-6"))["comments"][0]["body"] == "**hello**"
    assert call("add_comment", issue="DEMO-6", body="").is_error

    assert structured(call("delete_issue", issue="DEMO-6")) == {"deleted": "DEMO-6"}
    assert call("get_issue", issue="DEMO-6").is_error
    assert call("delete_issue", issue="DEMO-6").is_error
    with Session(factory.kw["bind"]) as db:
        assert db.scalar(select(m.Comment)) is None  # comments are deleted with the issue


def test_labels_and_list_issues_filters(factory):
    assert {x["name"] for x in structured(call("list_labels"))} == {"Bug", "Feature", "Improvement"}
    assert structured(call("create_label", name="Urgent", color="#ff0000"))["color"] == "#ff0000"
    structured(call("create_issue", team="DEMO", title="a", status="Todo"))
    structured(call("create_issue", team="DEMO", title="b", status="Todo"))
    structured(call("create_issue", team="DEMO", title="c"))
    todo = structured(call("list_issues", team="DEMO", status="todo"))
    assert {i["title"] for i in todo} >= {"a", "b"} and all(i["status"]["name"] == "Todo" for i in todo)
    assert len(structured(call("list_issues", team="DEMO", limit=2))) == 2
    assert len(structured(call("list_issues", team="DEMO", status="started"))) == 1


def test_update_project(factory):
    res = structured(call("update_project", project_id=1, status="completed", target_date="2027-03-01", lead="Alex"))
    assert res["status"] == "completed" and res["target_date"] == "2027-03-01" and res["lead"]["name"] == "Alex"
    assert res["name"] == "Getting started"  # untouched
    cleared = structured(call("update_project", project_id=1, lead="", target_date=""))
    assert cleared["lead"] is None and cleared["target_date"] is None
    assert call("update_project", project_id=1, status="bogus").is_error
    assert call("update_project", project_id=99, name="x").is_error
    assert "Nothing to update" in call("update_project", project_id=1).content[0].text
