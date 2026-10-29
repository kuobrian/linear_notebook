from sqlalchemy import func, select
from sqlalchemy.orm import Session

from local_linear import models as m
from local_linear.db import init_db, make_engine
from local_linear.seed import seed


def test_seed_populates_once():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as db:
        seed(db)
        seed(db)  # idempotent: second call is a no-op
        assert db.scalar(select(func.count()).select_from(m.Team)) == 1
        assert db.scalar(select(func.count()).select_from(m.Issue)) == 5
        assert db.scalar(select(func.count()).select_from(m.Cycle)) == 1
        team = db.scalar(select(m.Team))
        assert team.issue_counter == 5
