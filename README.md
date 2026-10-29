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
| `src/local_linear/seed.py` | demo data |
| `src/local_linear/static/` | single-page UI (hash routing, no build step) |
| `tests/` | API and seed tests (in-memory SQLite) |

## UI shortcuts

`C` new issue · `/` focus search · `Esc` close dialog · `Ctrl+Enter` submit the new-issue dialog.
Drag cards between columns on the board to change status.
