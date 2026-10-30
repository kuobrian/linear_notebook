# Local Linear

**English** · [繁體中文](README.zh-TW.md)

A local, Linear-style issue tracker that runs on your own machine. Plan work with teams, issues
(`ENG-12`), workflow statuses, priorities, labels, sub-issues, comments, projects with milestones
and documents, and cycles, in a fast list or board view. Built with FastAPI, SQLAlchemy and SQLite;
the UI is plain JavaScript with no build step. It also ships an [MCP](https://modelcontextprotocol.io)
server so an AI assistant such as Claude can create projects and issues for you.

![Board view](docs/images/issues-board.png)

## Contents

- [Requirements](#requirements) · [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [Configuration](#configuration)
- [REST API](#rest-api)
- [MCP server](#mcp-server)
- [Development](#development) · [Limitations](#limitations)

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs the right Python for you; the project needs Python 3.12+)
- A modern browser

Install uv if you do not have it:

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick start

```bash
git clone https://github.com/kuobrian/linear_notebook.git
cd linear_notebook
uv sync
uv run local-linear
```

Open <http://127.0.0.1:8000>. The first start creates `local_linear.db` in the current directory
and fills it with a small demo workspace (team `DEMO`, a few issues, one project) so you can click
around straight away. Use `--port 9000` to change the port and `--reload` while developing.
To start empty instead, run with `LOCAL_LINEAR_SEED=0`.

## Using the app

### Create a team, then issues

Everything lives in a **team**; its key (for example `ENG`) prefixes issue ids like `ENG-1`.
On an empty workspace, **New issue** first asks you to create a team. Each new team gets the
statuses Backlog, Todo, In Progress, Done and Canceled. Add more teams any time with **+ New team**
in the sidebar, and click a team to see only its issues.

Press **C** anywhere (or click **New issue**) to open the dialog. Give it a title, then optionally
a description, status, priority, assignee, project and labels. **Ctrl+Enter** creates it.

![New issue dialog](docs/images/new-issue.png)

### List and board

The default view is a list grouped by status. Each row shows priority, id, status, title, labels,
project, sub-issue and comment counts, created date and assignee.

![List view](docs/images/issues-list.png)

- **All / Active / Backlog** tabs narrow the list (Active means Todo and In Progress).
- Filter by priority, assignee or label, or search titles and descriptions: type in the search box
  (press **/** to jump to it) and press **Enter**.
- Switch to **Board** to see one column per status. **Drag a card to another column to change its
  status.** The **+** on a column or group creates an issue in that status.

### Work on an issue

Click an issue to open it. Title and description save automatically when you click away.
Use the panel on the right for status, priority, assignee, project, estimate, due date and labels.
Below the description you can add **sub-issues** (type a title and press Enter), and write
**comments**. Comments are posted as the person chosen under **Signed in as** in the sidebar.

![Issue detail](docs/images/issue-detail.png)

### Projects

**Projects** lists every project as a card with its status, lead and a progress bar (completed
issues out of all non-canceled issues). Open one to edit its status, priority, lead and start/target
dates, write a description, add **milestones**, and keep **documents** (click a document to edit it;
it saves when you click away). Issues in the project are listed at the bottom, and you can assign an
issue to a project from its detail panel.

![Project page](docs/images/project.png)

### Good to know

- The sidebar's **Toggle theme** switches between light and dark.
- Users and labels have no screens yet. Create them through the [REST API](#rest-api) (the demo data
  includes the users *Me* and *Alex* and three labels). Cycles are also API-only for now.
- Your data is the single SQLite file. Copy it to back up, delete it to start over.

## Configuration

| Variable | Default | Purpose |
| -- | -- | -- |
| `LOCAL_LINEAR_DB` | `sqlite:///local_linear.db` | SQLAlchemy database URL. The default path is relative to the directory you start the app from. |
| `LOCAL_LINEAR_SEED` | `1` | Set to `0` to skip creating demo data on an empty database. |

## REST API

Everything the UI does goes through a JSON API under `/api`. Interactive documentation with every
endpoint is at <http://127.0.0.1:8000/docs>. A few examples (these were run against a fresh
database):

```bash
BASE=http://127.0.0.1:8000
JSON='Content-Type: application/json'

# create a team (it gets the five default statuses: ids 1-5 in a fresh database)
curl -X POST $BASE/api/teams -H "$JSON" -d '{"key":"ENG","name":"Engineering"}'

# create an issue; the response includes its identifier (ENG-1)
curl -X POST $BASE/api/issues -H "$JSON" -d '{"team":"ENG","title":"Fix login bug","priority":2}'

# move it to In Progress (status ids are listed by GET /api/teams)
curl -X PATCH $BASE/api/issues/ENG-1 -H "$JSON" -d '{"status_id":3}'

# comment on it
curl -X POST $BASE/api/issues/ENG-1/comments -H "$JSON" -d '{"body":"Reproduced on staging."}'

# create a project, then put the issue in it
curl -X POST $BASE/api/projects -H "$JSON" -d '{"team":"ENG","name":"Auth revamp","status":"started","target_date":"2026-12-31"}'
curl -X PATCH $BASE/api/issues/ENG-1 -H "$JSON" -d '{"project_id":1}'

# filter and search issues
curl "$BASE/api/issues?team=ENG&priority=2&q=login"

# users and labels (UI has no screen for these yet)
curl -X POST $BASE/api/users  -H "$JSON" -d '{"name":"Sam","email":"sam@example.com"}'
curl -X POST $BASE/api/labels -H "$JSON" -d '{"name":"Bug","color":"#eb5757"}'
```

Notes: priority is `0` none, `1` urgent, `2` high, `3` medium, `4` low. Send `null` to clear a
field in a `PATCH` (for example `{"assignee_id": null}`); fields you leave out are unchanged.
Errors come back as `{"detail": "..."}` with a 4xx status.

## MCP server

`local-linear-mcp` is an MCP server (stdio) that lets an MCP client such as Claude manage the same
workspace the web UI shows. Anything it creates is in the database right away; reload the page to
see it in the UI.

| Tool | What it does |
| -- | -- |
| `list_teams` / `create_team` | list teams and their keys / create a team (`ENG`) |
| `create_project` | create a project: team, name, summary, description, status, priority, color, lead, start/target date |
| `list_projects` / `get_project` | list projects with progress / one project with milestones and documents |
| `create_issue` / `list_issues` | create an issue (returns e.g. `ENG-12`) / list and search issues |

Register it with Claude Code (use absolute paths, adjusted to where you cloned the repo):

```bash
claude mcp add local-linear \
  -e LOCAL_LINEAR_DB=sqlite:////absolute/path/to/local_linear.db \
  -- uv run --project /absolute/path/to/linear_notebook local-linear-mcp
```

or in any client's JSON config:

```json
{
  "mcpServers": {
    "local-linear": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/linear_notebook", "local-linear-mcp"],
      "env": { "LOCAL_LINEAR_DB": "sqlite:////absolute/path/to/local_linear.db" }
    }
  }
}
```

Then ask the assistant, for example: *"Create a project called Billing revamp in team ENG, started,
targeting 2026-12-31."*

> **Use the same database file as the web app.** The default database path is relative to the
> working directory, and an MCP client usually starts the server from a different directory than you
> run the web app from. Point both at the same file with an absolute `LOCAL_LINEAR_DB`
> (`sqlite:///` plus an absolute path; on Windows e.g. `sqlite:///C:/Users/you/local_linear.db`),
> or they will use separate databases. The MCP server does not create demo data, so on a fresh
> database call `create_team` first.

## Development

```bash
uv run pytest        # API, seed and MCP tests (in-memory SQLite)
```

| Path | What |
| -- | -- |
| `src/local_linear/models.py` | SQLAlchemy models |
| `src/local_linear/api.py` | REST routes under `/api` |
| `src/local_linear/schemas.py` | Pydantic request/response models |
| `src/local_linear/mcp_server.py` | MCP server (stdio) |
| `src/local_linear/seed.py` | demo data |
| `src/local_linear/static/` | single-page UI (hash routing, no build step) |
| `tests/` | tests |
| `docs/images/` | README screenshots |

## Limitations

- Single user, no login or permissions; "Signed in as" only chooses who comments are attributed to.
- Descriptions, comments and documents are plain text (no Markdown rendering).
- No real-time collaboration, notifications or Git integration.
- Users, labels and cycles can only be managed through the API for now.
