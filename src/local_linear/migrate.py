"""Copy every row from one database to another, e.g. SQLite to PostgreSQL or back."""

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import Engine

from .db import Base, init_db


class CopyError(Exception):
    """The copy cannot run; the message is safe to show to the user."""


def table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables}


def copy_database(source: Engine, target: Engine) -> dict[str, int]:
    """Create the tables in ``target`` and copy all rows, ids included. Returns rows copied per table.

    ``target`` must be empty. All rows go in one transaction, so a failure leaves it untouched.
    """
    init_db(target)
    used = [name for name, n in table_counts(target).items() if n]
    if used:
        raise CopyError("The target database is not empty (" + ", ".join(used) + "). Use a new, empty database.")

    copied = {}
    with source.connect() as src, target.begin() as dst:
        for table in Base.metadata.sorted_tables:
            rows = [dict(r) for r in src.execute(select(table)).mappings()]
            # A row may point at one inserted after it (an issue re-parented to a newer issue), so
            # self references go in as NULL first and are filled in once every row exists.
            self_refs = [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]
            fixups = []
            for r in rows:
                for col in self_refs:
                    if r[col] is not None:
                        fixups.append((r["id"], col, r[col]))
                        r[col] = None
            if rows:
                dst.execute(insert(table), rows)
            for row_id, col, value in fixups:
                dst.execute(update(table).where(table.c.id == row_id).values({col: value}))
            copied[table.name] = len(rows)
        if target.dialect.name == "postgresql":
            # Rows were inserted with explicit ids, so the id counters must be moved past them.
            for table in Base.metadata.sorted_tables:
                if "id" in table.c:
                    dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
                        f"EXISTS (SELECT 1 FROM \"{table.name}\"))"
                    ))
    return copied
