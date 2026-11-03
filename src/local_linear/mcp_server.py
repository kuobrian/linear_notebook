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
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import api
from . import models as m
from . import schemas as s
from .auth import token, token_ok
from .db import SessionLocal, init_db
from .hosts import allowed_hosts

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


def _ref(issue: str) -> str:
    """Issues are addressed by identifier only: a bare number would be read as an internal row id."""
    issue = issue.strip()
    if not api.ISSUE_ID.match(issue):
        raise ToolError(f"{issue!r} is not an issue identifier; use one like 'ENG-12'")
    return issue


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


@mcp.tool()
def delete_label(label_id: int) -> dict:
    """Permanently delete a label (id from list_labels); issues lose it. Cannot be undone."""
    with _db() as db:
        api.delete_label(label_id, db)
        return {"deleted": label_id}


@mcp.tool()
def delete_project(project_id: int) -> dict:
    """Permanently delete a project with its milestones and documents. Its issues are kept. Cannot be undone."""
    with _db() as db:
        api.delete_project(project_id, db)
        return {"deleted": project_id}


# ---- milestones and documents ----------------------------------------------
@mcp.tool()
def create_milestone(project_id: int, name: str, description: str = "", target_date: str | None = None) -> dict:
    """Add a milestone to a project. Returns it with its id (also listed by get_project).

    Args:
        project_id: Project id (see list_projects).
        target_date: ISO date, e.g. "2026-12-31".
    """
    with _db() as db:
        body = s.MilestoneIn(name=name, description=description,
                             target_date=_date(target_date, "target_date") if target_date else None)
        return _json(api.create_milestone(project_id, body, db))


@mcp.tool()
def delete_milestone(milestone_id: int) -> dict:
    """Permanently delete a milestone (id from get_project). Its issues are kept. Cannot be undone."""
    with _db() as db:
        api.delete_milestone(milestone_id, db)
        return {"deleted": milestone_id}


@mcp.tool()
def create_document(title: str, content: str = "", project_id: int | None = None) -> dict:
    """Create a document (Markdown content), optionally inside a project. Returns it with its id."""
    with _db() as db:
        body = s.DocumentIn(title=title, content=content, project_id=project_id)
        return _json(s.DocumentOut.model_validate(api.create_document(body, db)))


@mcp.tool()
def update_document(document_id: int, title: str | None = None, content: str | None = None) -> dict:
    """Change a document's title and/or content (the new content replaces the old). Only passed fields change."""
    fields = {k: v for k, v in (("title", title), ("content", content)) if v is not None}
    if not fields:
        raise ToolError("Nothing to update: pass at least one field")
    with _db() as db:
        return _json(s.DocumentOut.model_validate(api.update_document(document_id, s.DocumentPatch(**fields), db)))


@mcp.tool()
def delete_document(document_id: int) -> dict:
    """Permanently delete a document (id from get_project or create_document). Cannot be undone."""
    with _db() as db:
        api.delete_document(document_id, db)
        return {"deleted": document_id}


# ---- cycles ----------------------------------------------------------------
@mcp.tool()
def list_cycles(team: str | None = None) -> list[dict]:
    """List cycles (newest first), optionally for one team key. Use a cycle's `id` in the other cycle tools
    and in create_issue / update_issue."""
    with _db() as db:
        return [_json(s.CycleOut.model_validate(c)) for c in api.list_cycles(team, db)]


@mcp.tool()
def create_cycle(team: str, starts_at: str, ends_at: str, name: str | None = None) -> dict:
    """Create a cycle. Its number is the team's next free one.

    Args:
        team: Team key, e.g. "ENG".
        starts_at: ISO date, e.g. "2026-11-02".
        ends_at: ISO date on or after starts_at.
        name: Optional name.
    """
    with _db() as db:
        body = s.CycleIn(team=team, name=name, starts_at=_date(starts_at, "starts_at"), ends_at=_date(ends_at, "ends_at"))
        return _json(s.CycleOut.model_validate(api.create_cycle(body, db)))


@mcp.tool()
def update_cycle(cycle_id: int, name: str | None = None, starts_at: str | None = None, ends_at: str | None = None) -> dict:
    """Change a cycle. Only the fields you pass are changed.

    Args:
        cycle_id: Cycle id (see list_cycles).
        name: New name, or "" to clear it.
        starts_at: ISO date.
        ends_at: ISO date, on or after the start.
    """
    fields: dict = {}
    if name is not None:
        fields["name"] = name or None
    if starts_at is not None:
        fields["starts_at"] = _date(starts_at, "starts_at")
    if ends_at is not None:
        fields["ends_at"] = _date(ends_at, "ends_at")
    if not fields:
        raise ToolError("Nothing to update: pass at least one field")
    with _db() as db:
        return _json(s.CycleOut.model_validate(api.update_cycle(cycle_id, s.CyclePatch(**fields), db)))


@mcp.tool()
def delete_cycle(cycle_id: int) -> dict:
    """Permanently delete a cycle. Its issues are kept but leave the cycle. Cannot be undone."""
    with _db() as db:
        api.delete_cycle(cycle_id, db)
        return {"deleted": cycle_id}


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
    cycle_id: int | None = None,
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
        cycle_id: Cycle to put the issue in (see list_cycles).
    """
    with _db() as db:
        team_row = api._team(db, team)
        body = s.IssueIn(
            team=team, title=title, description=description, priority=priority, estimate=estimate,
            status_id=_status(team_row, status).id if status else None,
            label_ids=_label_ids(db, labels) if labels else [],
            assignee_id=_user_id(db, assignee), project_id=project_id, cycle_id=cycle_id,
            due_date=_date(due_date, "due_date") if due_date else None,
            parent_id=api._issue(db, _ref(parent)).id if parent else None,
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
    cycle_id: int | None = None,
) -> dict:
    """Change an issue. Only the fields you pass are changed.

    Args:
        issue: Identifier such as "ENG-12".
        status: Status name such as "In Progress" or "Done", or a type like "completed".
        priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        labels: The complete list of label names (replaces the current labels; [] removes all).
        assignee: Name of an existing user, or "" to unassign.
        project_id: Project id, or 0 to remove the issue from its project.
        cycle_id: Cycle id (see list_cycles), or 0 to remove the issue from its cycle.
        due_date: ISO date, or "" to clear.
    """
    issue = _ref(issue)
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
        if cycle_id is not None:
            fields["cycle_id"] = cycle_id or None
        if due_date is not None:
            fields["due_date"] = _date(due_date, "due_date") if due_date else None
        if not fields:
            raise ToolError("Nothing to update: pass at least one field")
        return _json(api.update_issue(issue, s.IssuePatch(**fields), db))


@mcp.tool()
def get_issue(issue: str) -> dict:
    """Get one issue by identifier (e.g. "ENG-12") with its comments and sub-issues."""
    issue = _ref(issue)
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
    if project_id is not None and not 0 < project_id < 2**31:
        raise ToolError(f"Project {project_id} not found")
    with _db() as db:
        issues = api.list_issues(
            team=team, status_id=None, status_type=None, assignee_id=None, unassigned=False,
            project_id=project_id, milestone_id=None, cycle_id=None, label_id=None, priority=None,
            parent_id=None, q=query, status_name=status, order_by="priority", limit=min(max(limit, 1), 1000), db=db,
        )
        return [_json(i) for i in issues]


@mcp.tool()
def add_comment(issue: str, body: str, author: str | None = None) -> dict:
    """Comment on an issue (Markdown supported). `author` is the name of an existing user."""
    issue = _ref(issue)
    with _db() as db:
        comment = api.add_comment(issue, s.CommentIn(body=body, author_id=_user_id(db, author)), db)
        return _json(s.CommentOut.model_validate(comment))


@mcp.tool()
def delete_comment(comment_id: int) -> dict:
    """Permanently delete a comment (id from get_issue). Cannot be undone."""
    with _db() as db:
        api.delete_comment(comment_id, db)
        return {"deleted": comment_id}


@mcp.tool()
def delete_issue(issue: str) -> dict:
    """Permanently delete an issue (and its comments). Sub-issues are kept. Cannot be undone."""
    issue = _ref(issue)
    with _db() as db:
        identifier = api._issue(db, issue).identifier
        api.delete_issue(issue, db)
        return {"deleted": identifier}


def transport_security() -> TransportSecuritySettings:
    """Refuse foreign Host/Origin headers on every bind address (the SDK only does so for loopback)."""
    hosts = allowed_hosts()
    return TransportSecuritySettings(
        allowed_hosts=[*hosts, *(f"{h}:*" for h in hosts)],
        allowed_origins=[f"http://{h}:*" for h in hosts],
    )


def with_token(app):
    """ASGI wrapper that answers 401 unless LOCAL_LINEAR_TOKEN is unset or sent as a Bearer token.

    Pure ASGI, not BaseHTTPMiddleware, so streamed (SSE) responses are not buffered.
    """
    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not token_ok(headers.get("authorization", ""), ""):
                body = b"Unauthorized: send 'Authorization: Bearer <LOCAL_LINEAR_TOKEN>'"
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await app(scope, receive, send)

    return guarded


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
        if args.host not in ("127.0.0.1", "localhost", "::1") and not token():
            # Without a token anyone who can reach the port can read and write the workspace.
            print(f"WARNING: serving without authentication on {args.host}; set LOCAL_LINEAR_TOKEN "
                  "or only do this on a trusted network.", file=sys.stderr)
        import uvicorn

        app = mcp.streamable_http_app(streamable_http_path=args.path, host=args.host,
                                      transport_security=transport_security())
        uvicorn.run(with_token(app), host=args.host, port=args.port, log_level="info")
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
