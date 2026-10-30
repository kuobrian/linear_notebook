"""MCP server exposing Local Linear to MCP clients over stdio.

Run with ``uv run local-linear-mcp``. It talks to the same database as the web app
(``LOCAL_LINEAR_DB``), so projects created here show up in the UI right away.

stdout carries the MCP protocol, so nothing in this module may print to it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import api
from . import models as m
from . import schemas as s
from .db import SessionLocal, init_db

mcp = MCPServer(
    "local-linear",
    instructions=(
        "Manage a local Linear-style workspace. Call list_teams first to get valid team keys "
        "(e.g. 'ENG'), then create_project / create_issue."
    ),
)


@contextmanager
def _db() -> Iterator[Session]:
    """A session that reports failures to the MCP client with a readable message.

    The SDK hides the text of ordinary exceptions from clients; only ToolError messages are
    sent back, and the client (usually an LLM) needs them to correct its call.
    """
    with SessionLocal() as db:
        try:
            yield db
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            raise ToolError(f"Invalid input: {problems}") from exc


def _json(model) -> dict:
    return model.model_dump(mode="json")


def _user_id(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    user = db.scalar(select(m.User).where(func.lower(m.User.name) == name.lower()))
    if not user:
        known = ", ".join(u.name for u in db.scalars(select(m.User))) or "none"
        raise ToolError(f"User {name!r} not found (known users: {known})")
    return user.id


@mcp.tool()
def list_teams() -> list[dict]:
    """List teams with their keys and workflow statuses. Team keys are needed by other tools."""
    with _db() as db:
        return [_json(s.TeamOut.model_validate(t)) for t in api.list_teams(db)]


@mcp.tool()
def create_team(key: str, name: str) -> dict:
    """Create a team. The key (letters/digits, max 10, e.g. "ENG") prefixes issue ids like ENG-1."""
    with _db() as db:
        return _json(s.TeamOut.model_validate(api.create_team(s.TeamIn(key=key, name=name), db)))


@mcp.tool()
def create_project(
    team: str,
    name: str,
    summary: str = "",
    description: str = "",
    status: str = "planned",
    priority: int = 0,
    color: str = "#4cb782",
    lead: str | None = None,
    start_date: date | None = None,
    target_date: date | None = None,
) -> dict:
    """Create a project.

    Args:
        team: Team key, e.g. "ENG" (see list_teams).
        name: Project name.
        summary: One-line summary.
        description: Longer description.
        status: One of backlog, planned, started, paused, completed, canceled.
        priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        color: Hex color such as "#4cb782".
        lead: Name of the project lead (an existing user).
        start_date: ISO date, e.g. "2026-11-01".
        target_date: ISO date, e.g. "2026-12-31".
    """
    with _db() as db:
        body = s.ProjectIn(
            team=team, name=name, summary=summary, description=description, status=status,
            priority=priority, color=color, lead_id=_user_id(db, lead),
            start_date=start_date, target_date=target_date,
        )
        return _json(api.create_project(body, db))


@mcp.tool()
def list_projects(team: str | None = None, status: str | None = None) -> list[dict]:
    """List projects with progress, optionally filtered by team key and/or status."""
    with _db() as db:
        return [_json(p) for p in api.list_projects(team, status, db)]


@mcp.tool()
def get_project(project_id: int) -> dict:
    """Get one project with its milestones and documents."""
    with _db() as db:
        return _json(api.get_project(project_id, db))


@mcp.tool()
def create_issue(
    team: str,
    title: str,
    description: str = "",
    priority: int = 0,
    assignee: str | None = None,
    project_id: int | None = None,
) -> dict:
    """Create an issue in a team's backlog. Returns the issue including its identifier, e.g. ENG-12."""
    with _db() as db:
        body = s.IssueIn(
            team=team, title=title, description=description, priority=priority,
            assignee_id=_user_id(db, assignee), project_id=project_id,
        )
        return _json(api.create_issue(body, db))


@mcp.tool()
def list_issues(team: str | None = None, project_id: int | None = None, query: str | None = None) -> list[dict]:
    """List issues, optionally filtered by team key, project id or a text search."""
    with _db() as db:
        issues = api.list_issues(
            team=team, status_id=None, status_type=None, assignee_id=None, unassigned=False,
            project_id=project_id, milestone_id=None, cycle_id=None, label_id=None, priority=None,
            parent_id=None, q=query, order_by="priority", limit=200, db=db,
        )
        return [_json(i) for i in issues]


def main() -> None:
    init_db()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
