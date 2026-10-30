# Local Linear

A local, Linear-style issue tracker: teams, issues (`KEY-n`), workflow statuses, priorities,
labels, sub-issues, comments, projects with milestones and documents, cycles, and
list / board views. FastAPI + SQLAlchemy + SQLite, with a build-free vanilla-JS UI.

## Run

```bash
uv sync
uv run local-linear            # http://127.0.0.1:8000
uv run local-linear --port 9000 --reload
```

The first start creates `local_linear.db` in the current directory and seeds a small demo
workspace. Environment variables:

| Variable | Default | Purpose |
| -- | -- | -- |
| `LOCAL_LINEAR_DB` | `sqlite:///local_linear.db` | SQLAlchemy database URL |
| `LOCAL_LINEAR_SEED` | `1` | set to `0` to start with an empty workspace |

## MCP server

`local-linear-mcp` is an [MCP](https://modelcontextprotocol.io) server (stdio) that lets an MCP
client such as Claude manage the same workspace the web UI shows.

| Tool | What it does |
| -- | -- |
| `list_teams` / `create_team` | list teams and their keys / create a team (`ENG`) |
| `create_project` | create a project: team, name, summary, description, status, priority, color, lead, start/target date |
| `list_projects` / `get_project` | list projects with progress / one project with milestones and documents |
| `create_issue` / `list_issues` | create an issue (returns e.g. `ENG-12`) / list and search issues |

Register it with Claude Code (use absolute paths, adjust to where you cloned the repo):

```bash
claude mcp add local-linear \
  -e LOCAL_LINEAR_DB=sqlite:////absolute/path/to/local_linear.db \
  -- uv run --project /absolute/path/to/local_linear local-linear-mcp
```

or in any client's JSON config:

```json
{
  "mcpServers": {
    "local-linear": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/local_linear", "local-linear-mcp"],
      "env": { "LOCAL_LINEAR_DB": "sqlite:////absolute/path/to/local_linear.db" }
    }
  }
}
```

> The default database path is relative to the working directory, and an MCP client usually
> starts the server from a different directory than you run the web app from. Point both at
> the same file with an absolute `LOCAL_LINEAR_DB` (`sqlite:///` + an absolute path; on
> Windows e.g. `sqlite:///C:/Users/you/local_linear.db`), or they will use separate databases.
> The server does not seed demo data; create a team first with `create_team` on a fresh database.

## Test

```bash
uv run pytest
```

## Layout

| Path | What |
| -- | -- |
| `src/local_linear/models.py` | SQLAlchemy models |
| `src/local_linear/api.py` | REST routes under `/api` (interactive docs at `/docs`) |
| `src/local_linear/schemas.py` | Pydantic request/response models |
| `src/local_linear/mcp_server.py` | MCP server (stdio) |
| `src/local_linear/seed.py` | demo data |
| `src/local_linear/static/` | single-page UI (hash routing, no build step) |
| `tests/` | API and seed tests (in-memory SQLite) |

## UI shortcuts

`C` new issue · `/` focus search · `Esc` close dialog · `Ctrl+Enter` submit the new-issue dialog.
Drag cards between columns on the board to change status.
