from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .api import DEFAULT_STATUSES


def seed(db: Session) -> None:
    """Populate an empty database with a small demo workspace."""
    if db.scalar(select(m.Team.id).limit(1)):
        return

    me = m.User(name="Me", email="me@example.com")
    teammate = m.User(name="Alex", email="alex@example.com")
    db.add_all([me, teammate])

    team = m.Team(key="DEMO", name="Demo")
    for pos, (name, typ, color) in enumerate(DEFAULT_STATUSES):
        team.statuses.append(m.Status(name=name, type=typ, position=pos, color=color))
    db.add(team)

    bug = m.Label(name="Bug", color="#eb5757")
    feature = m.Label(name="Feature", color="#bb87fc")
    improvement = m.Label(name="Improvement", color="#4ea7fc")
    db.add_all([bug, feature, improvement])

    today = date.today()
    project = m.Project(
        team=team,
        name="Getting started",
        summary="Try out issues, projects and milestones",
        description="A sample project. Edit or delete it any time.",
        status="started",
        priority=2,
        lead=me,
        start_date=today,
        target_date=today + timedelta(days=30),
    )
    project.milestones.append(m.Milestone(name="Beta", target_date=today + timedelta(days=14)))
    project.documents.append(m.Document(title="Project notes", content="# Notes\n\nWrite anything here."))
    db.add(project)
    db.add(m.Cycle(team=team, number=1, starts_at=today, ends_at=today + timedelta(days=14)))
    db.flush()

    by_type = {s.type: s for s in team.statuses}
    samples = [
        ("Welcome to Local Linear", "unstarted", 3, me, [feature]),
        ("Press C to create a new issue", "started", 2, me, [improvement]),
        ("Drag cards between columns on the board", "backlog", 0, None, [feature]),
        ("Fix typo on the login page", "backlog", 4, teammate, [bug]),
        ("Ship the first release", "completed", 1, teammate, []),
    ]
    for title, typ, prio, assignee, labels in samples:
        team.issue_counter += 1
        status = by_type[typ]
        db.add(
            m.Issue(
                team=team,
                number=team.issue_counter,
                title=title,
                status=status,
                priority=prio,
                assignee=assignee,
                project=project,
                labels=labels,
            )
        )
    db.commit()
