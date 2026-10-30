"""MCP server exposing Local Linear to MCP clients over stdio.

Run with ``uv run local-linear-mcp`` (stdio) or ``uv run local-linear-mcp --transport http``
(streamable HTTP, default http://127.0.0.1:8765/mcp). It talks to the same database as the web app
(``LOCAL_LINEAR_DB``), so projects created here show up in the UI after a reload.

In stdio mode stdout carries the MCP protocol, so nothing in this module may print to it.
"""

import argparse
import sys
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
        "(e.g. 'ENG') and their status names, then create/update issues and projects. Issues are "
        "addressed by identifier such as 'ENG-12'. Status and labels are given by name; unknown "
        "names are rejected with the list of valid ones."
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


def _status(team: m.Team, name: str) -> m.Status:
    """Find a team status by its name ('In Progress') or its type ('started', 'completed', ...)."""
    key = name.strip().lower()
    for st in team.statuses:
        if st.name.lower() == key:
            return st
    for st in team.statuses:
        if st.type == key:
            return st
    valid = ", ".join(st.name for st in team.statuses)
    raise ToolError(f"Status {name!r} not found in team {team.key} (valid: {valid})")


def _label_ids(db: Session, names: list[str]) -> list[int]:
    by_name = {label.name.lower(): label for label in db.scalars(select(m.Label))}
    missing = [n for n in names if n.strip().lower() not in by_name]
    if missing:
        known = ", ".join(sorted(label.name for label in by_name.values())) or "none"
        raise ToolError(f"Unknown label(s): {', '.join(missing)} (known labels: {known}; create one with create_label)")
    return [by_name[n.strip().lower()].id for n in names]


def _date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{field} must be an ISO date like 2026-12-31, got {value!r}") from None


# ---- teams -----------------------------------------------------------------
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


# ---- labels ----------------------------------------------------------------
@mcp.tool()
def list_labels() -> list[dict]:
    """List labels. Use their names in create_issue / update_issue."""
    with _db() as db:
        return [_json(s.LabelOut.model_validate(x)) for x in api.list_labels(db)]


@mcp.tool()
def create_label(name: str, color: str = "#5e6ad2") -> dict:
    """Create a label (e.g. "Bug", color "#eb5757")."""
    with _db() as db:
        return _json(s.LabelOut.model_validate(api.create_label(s.LabelIn(name=name, color=color), db)))


# ---- projects --------------------------------------------------------------
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
        description: Longer description (Markdown supported).
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
def update_project(
    project_id: int,
    name: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    lead: str | None = None,
    start_date: str | None = None,
    target_date: str | None = None,
) -> dict:
    """Change a project. Only the fields you pass are changed.

    Args:
        project_id: Project id (see list_projects).
        status: One of backlog, planned, started, paused, completed, canceled.
        priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        lead: Name of an existing user, or "" to remove the lead.
        start_date: ISO date, or "" to clear.
        target_date: ISO date, or "" to clear.
    """
    with _db() as db:
        fields: dict = {}
        for key, value in (("name", name), ("summary", summary), ("description", description),
                           ("status", status), ("priority", priority)):
            if value is not None:
                fields[key] = value
        if lead is not None:
            fields["lead_id"] = _user_id(db, lead)
        if start_date is not None:
            fields["start_date"] = _date(start_date, "start_date") if start_date else None
        if target_date is not None:
            fields["target_date"] = _date(target_date, "target_date") if target_date else None
        if not fields:
            raise ToolError("Nothing to update: pass at least one field")
        return _json(api.update_project(project_id, s.ProjectPatch(**fields), db))


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


# ---- issues ----------------------------------------------------------------
@mcp.tool()
def create_issue(
    team: str,
    title: str,
    description: str = "",
    status: str | None = None,
    priority: int = 0,
    labels: list[str] | None = None,
    assignee: str | None = None,
    project_id: int | None = None,
    estimate: int | None = None,
    due_date: str | None = None,
    parent: str | None = None,
) -> dict:
    """Create an issue. Returns it including its identifier, e.g. ENG-12.

    Args:
        team: Team key, e.g. "ENG".
        title: Issue title.
        description: Markdown supported.
        status: Status name such as "Todo" or "In Progress" (default: the team's Backlog).
            See list_teams for valid names. A status type like "started" also works.
        priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        labels: Label names, e.g. ["Bug"]. Unknown names are an error (see list_labels / create_label).
        assignee: Name of an existing user.
        project_id: Project to put the issue in.
        estimate: Estimate points.
        due_date: ISO date, e.g. "2026-12-31".
        parent: Identifier of the parent issue, making this a sub-issue (e.g. "ENG-3").
    """
    with _db() as db:
        team_row = api._team(db, team)
        body = s.IssueIn(
            team=team, title=title, description=description, priority=priority, estimate=estimate,
            status_id=_status(team_row, status).id if status else None,
            label_ids=_label_ids(db, labels) if labels else [],
            assignee_id=_user_id(db, assignee), project_id=project_id,
            due_date=_date(due_date, "due_date") if due_date else None,
            parent_id=api._issue(db, parent).id if parent else None,
        )
        return _json(api.create_issue(body, db))


@mcp.tool()
def update_issue(
    issue: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    labels: list[str] | None = None,
    assignee: str | None = None,
    project_id: int | None = None,
    estimate: int | None = None,
    due_date: str | None = None,
) -> dict:
    """Change an issue. Only the fields you pass are changed.

    Args:
        issue: Identifier such as "ENG-12".
        status: Status name such as "In Progress" or "Done", or a type like "completed".
        priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        labels: The complete list of label names (replaces the current labels; [] removes all).
        assignee: Name of an existing user, or "" to unassign.
        project_id: Project id, or 0 to remove the issue from its project.
        due_date: ISO date, or "" to clear.
    """
    with _db() as db:
        row = api._issue(db, issue)
        fields: dict = {}
        for key, value in (("title", title), ("description", description), ("priority", priority),
                           ("estimate", estimate)):
            if value is not None:
                fields[key] = value
        if status is not None:
            fields["status_id"] = _status(row.team, status).id
        if labels is not None:
            fields["label_ids"] = _label_ids(db, labels)
        if assignee is not None:
            fields["assignee_id"] = _user_id(db, assignee)
        if project_id is not None:
            fields["project_id"] = project_id or None
        if due_date is not None:
            fields["due_date"] = _date(due_date, "due_date") if due_date else None
        if not fields:
            raise ToolError("Nothing to update: pass at least one field")
        return _json(api.update_issue(issue, s.IssuePatch(**fields), db))


@mcp.tool()
def get_issue(issue: str) -> dict:
    """Get one issue by identifier (e.g. "ENG-12") with its comments and sub-issues."""
    with _db() as db:
        return _json(api.get_issue(issue, db))


@mcp.tool()
def list_issues(
    team: str | None = None,
    project_id: int | None = None,
    query: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """List issues (most important first), optionally filtered.

    Args:
        team: Team key.
        project_id: Only issues in this project.
        query: Text to search for in titles and descriptions.
        status: Status name ("In Progress") or type ("started").
        limit: Maximum number of issues to return (1-1000, default 200). If the result has exactly
            this many items there may be more; narrow the filters or raise the limit.
    """
    with _db() as db:
        issues = api.list_issues(
            team=team, status_id=None, status_type=None, assignee_id=None, unassigned=False,
            project_id=project_id, milestone_id=None, cycle_id=None, label_id=None, priority=None,
            parent_id=None, q=query, order_by="priority", limit=min(max(limit, 1), 1000), db=db,
        )
        if status:
            key = status.strip().lower()
            issues = [i for i in issues if i.status.name.lower() == key or i.status.type == key]
        return [_json(i) for i in issues]


@mcp.tool()
def add_comment(issue: str, body: str, author: str | None = None) -> dict:
    """Comment on an issue (Markdown supported). `author` is the name of an existing user."""
    with _db() as db:
        comment = api.add_comment(issue, s.CommentIn(body=body, author_id=_user_id(db, author)), db)
        return _json(s.CommentOut.model_validate(comment))


@mcp.tool()
def delete_issue(issue: str) -> dict:
    """Permanently delete an issue (and its comments). Sub-issues are kept. Cannot be undone."""
    with _db() as db:
        identifier = api._issue(db, issue).identifier
        api.delete_issue(issue, db)
        return {"deleted": identifier}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="local-linear-mcp", description="Local Linear MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="stdio (default, launched by the MCP client) or http (streamable HTTP)")
    parser.add_argument("--host", default="127.0.0.1", help="http only; default is loopback")
    parser.add_argument("--port", type=int, default=8765, help="http only (default 8765)")
    parser.add_argument("--path", default="/mcp", help="http only: URL path of the endpoint")
    args = parser.parse_args(argv)

    init_db()
    if args.transport == "http":
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            # There is no authentication: anyone who can reach the port can read and write the workspace.
            print(f"WARNING: serving without authentication on {args.host}; only do this on a trusted network.",
                  file=sys.stderr)
        mcp.run("streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
