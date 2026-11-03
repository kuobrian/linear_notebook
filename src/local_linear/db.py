import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def normalize_url(url: str) -> str:
    """Accept the usual postgres:// and postgresql:// URLs and use the psycopg 3 driver for them."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str | None = None) -> Engine:
    """Engine for SQLite (default, a local file) or PostgreSQL, chosen by the URL.

    LOCAL_LINEAR_DB examples: ``sqlite:///local_linear.db``,
    ``postgresql://user:password@localhost:5432/local_linear``.
    """
    url = normalize_url(url or os.getenv("LOCAL_LINEAR_DB", "sqlite:///local_linear.db"))
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True  # survive restarts of the database server
        kwargs["connect_args"] = {"connect_timeout": 5}  # an unreachable host fails in seconds, not minutes
    if url in ("sqlite://", "sqlite:///:memory:"):
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def _unique_cycle_numbers(conn) -> None:
    """Older databases may hold two cycles with one number; renumber the later ones so the index can be built."""
    seen: dict[int, set[int]] = {}
    top: dict[int, int] = {}
    rows = conn.execute(text("SELECT id, team_id, number FROM cycles ORDER BY id")).all()
    for _, team, number in rows:
        top[team] = max(top.get(team, 0), number)
    for cid, team, number in rows:
        if number in seen.setdefault(team, set()):
            top[team] += 1
            number = top[team]
            conn.execute(text("UPDATE cycles SET number = :n WHERE id = :i"), {"n": number, "i": cid})
        seen[team].add(number)
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS cycles_team_number ON cycles (team_id, number)"))


# Append only, never edit or reorder: the position is the version recorded in schema_migrations.
# Each runs once, on every database (new ones too, so they must be idempotent).
MIGRATIONS = [_unique_cycle_numbers]


def migrate(eng: Engine) -> None:
    """Apply the migrations this database has not seen yet. Safe to call from several processes at once."""
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
        done = set(conn.scalars(text("SELECT version FROM schema_migrations")))
    for version, step in enumerate(MIGRATIONS, start=1):
        if version in done:
            continue
        try:
            with eng.begin() as conn:
                step(conn)
                conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
        except IntegrityError:  # another process recorded this version first; the step is idempotent
            pass


def init_db(eng: Engine | None = None) -> None:
    from . import models  # noqa: F401  (register tables)

    eng = eng or engine
    Base.metadata.create_all(eng)
    migrate(eng)
