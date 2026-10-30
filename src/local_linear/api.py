from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from . import markdown
from . import models as m
from . import schemas as s
from .db import get_session

router = APIRouter(prefix="/api")

DEFAULT_STATUSES = [
    ("Backlog", "backlog", "#bec2c8"),
    ("Todo", "unstarted", "#e2e2e2"),
    ("In Progress", "started", "#f2c94c"),
    ("Done", "completed", "#5e6ad2"),
    ("Canceled", "canceled", "#95a2b3"),
]


# ---- helpers ---------------------------------------------------------------
def _team(db: Session, key: str) -> m.Team:
    team = db.scalar(select(m.Team).where(func.upper(m.Team.key) == key.upper()))
    if not team:
        raise HTTPException(404, f"Team {key!r} not found")
    return team


def _get(db: Session, model, ident: int, label: str):
    obj = db.get(model, ident)
    if not obj:
        raise HTTPException(404, f"{label} {ident} not found")
    return obj


def _issue(db: Session, ref: str) -> m.Issue:
    if ref.isdigit():
        issue = db.get(m.Issue, int(ref))
    else:
        key, _, num = ref.rpartition("-")
        if not num.isdigit():
            raise HTTPException(404, f"Issue {ref!r} not found")
        issue = db.scalar(
            select(m.Issue).join(m.Team).where(func.upper(m.Team.key) == key.upper(), m.Issue.number == int(num))
        )
    if not issue:
        raise HTTPException(404, f"Issue {ref!r} not found")
    return issue


def _apply_status(issue: m.Issue, status: m.Status) -> None:
    if status.team_id != issue.team_id:
        raise HTTPException(422, "Status belongs to a different team")
    issue.status = status
    now = datetime.now(timezone.utc)
    issue.completed_at = now if status.type == "completed" else None
    issue.canceled_at = now if status.type == "canceled" else None


def _check_parent(db: Session, issue: m.Issue | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = _get(db, m.Issue, parent_id, "Parent issue")
    if issue is not None:
        node = parent
        while node is not None:
            if node.id == issue.id:
                raise HTTPException(422, "An issue cannot be its own ancestor")
            node = db.get(m.Issue, node.parent_id) if node.parent_id else None


def _labels(db: Session, ids: list[int]) -> list[m.Label]:
    found = list(db.scalars(select(m.Label).where(m.Label.id.in_(ids)))) if ids else []
    if len(found) != len(set(ids)):
        raise HTTPException(422, "Unknown label id")
    return found


def _counts(db: Session, issues: list[m.Issue]) -> tuple[dict[int, int], dict[int, int]]:
    ids = [i.id for i in issues]
    if not ids:
        return {}, {}
    subs = dict(
        db.execute(
            select(m.Issue.parent_id, func.count()).where(m.Issue.parent_id.in_(ids)).group_by(m.Issue.parent_id)
        ).all()
    )
    comments = dict(
        db.execute(
            select(m.Comment.issue_id, func.count()).where(m.Comment.issue_id.in_(ids)).group_by(m.Comment.issue_id)
        ).all()
    )
    return subs, comments


def _issue_out(issue: m.Issue, subs: dict[int, int], comments: dict[int, int], db: Session) -> s.IssueOut:
    parent = db.get(m.Issue, issue.parent_id) if issue.parent_id else None
    return s.IssueOut(
        id=issue.id,
        identifier=issue.identifier,
        team_id=issue.team_id,
        number=issue.number,
        title=issue.title,
        description=issue.description,
        status=s.StatusOut.model_validate(issue.status),
        priority=issue.priority,
        priority_name=m.PRIORITIES[issue.priority],
        estimate=issue.estimate,
        assignee=s.UserOut.model_validate(issue.assignee) if issue.assignee else None,
        project_id=issue.project_id,
        project_name=issue.project.name if issue.project else None,
        milestone_id=issue.milestone_id,
        cycle_id=issue.cycle_id,
        parent_id=issue.parent_id,
        parent_identifier=parent.identifier if parent else None,
        due_date=issue.due_date,
        labels=[s.LabelOut.model_validate(label) for label in issue.labels],
        sub_issue_count=subs.get(issue.id, 0),
        comment_count=comments.get(issue.id, 0),
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        completed_at=issue.completed_at,
        canceled_at=issue.canceled_at,
    )


def _issues_out(db: Session, issues: list[m.Issue]) -> list[s.IssueOut]:
    subs, comments = _counts(db, issues)
    return [_issue_out(i, subs, comments, db) for i in issues]


def _progress(db: Session, project_id: int) -> s.ProjectProgress:
    rows = db.execute(
        select(m.Status.type, func.count())
        .select_from(m.Issue)
        .join(m.Status, m.Issue.status_id == m.Status.id)
        .where(m.Issue.project_id == project_id)
        .group_by(m.Status.type)
    ).all()
    by_type = dict(rows)
    completed = by_type.get("completed", 0)
    started = by_type.get("started", 0)
    total = sum(n for t, n in by_type.items() if t != "canceled")
    return s.ProjectProgress(
        total=total, completed=completed, started=started, percent=round(completed / total * 100) if total else 0
    )


def _project_out(db: Session, p: m.Project) -> s.ProjectOut:
    return s.ProjectOut(
        id=p.id,
        team_id=p.team_id,
        name=p.name,
        summary=p.summary,
        description=p.description,
        status=p.status,
        priority=p.priority,
        color=p.color,
        lead=s.UserOut.model_validate(p.lead) if p.lead else None,
        start_date=p.start_date,
        target_date=p.target_date,
        progress=_progress(db, p.id),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _milestone_out(db: Session, ms: m.Milestone) -> s.MilestoneOut:
    rows = db.execute(
        select(m.Status.type, func.count())
        .select_from(m.Issue)
        .join(m.Status, m.Issue.status_id == m.Status.id)
        .where(m.Issue.milestone_id == ms.id)
        .group_by(m.Status.type)
    ).all()
    by_type = dict(rows)
    out = s.MilestoneOut.model_validate(ms)
    out.issue_count = sum(by_type.values())
    out.done_count = by_type.get("completed", 0)
    return out


def _check_project_status(value: str) -> None:
    if value not in m.PROJECT_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(m.PROJECT_STATUSES)}")


@router.post("/markdown", response_model=s.MarkdownOut)
def render_markdown(body: s.MarkdownIn):
    """Render Markdown to safe HTML (used for the comment preview)."""
    return s.MarkdownOut(html=markdown.render(body.text))


# ---- meta / teams / users / labels ----------------------------------------
@router.get("/meta")
def meta(db: Session = Depends(get_session)):
    return {
        "teams": [s.TeamOut.model_validate(t) for t in db.scalars(select(m.Team).order_by(m.Team.key))],
        "users": [s.UserOut.model_validate(u) for u in db.scalars(select(m.User).order_by(m.User.name))],
        "labels": [s.LabelOut.model_validate(x) for x in db.scalars(select(m.Label).order_by(m.Label.name))],
        "priorities": [{"value": k, "name": v} for k, v in m.PRIORITIES.items()],
        "project_statuses": list(m.PROJECT_STATUSES),
    }


@router.get("/teams", response_model=list[s.TeamOut])
def list_teams(db: Session = Depends(get_session)):
    return db.scalars(select(m.Team).order_by(m.Team.key)).all()


@router.post("/teams", response_model=s.TeamOut, status_code=201)
def create_team(body: s.TeamIn, db: Session = Depends(get_session)):
    key = body.key.upper()
    if db.scalar(select(m.Team).where(m.Team.key == key)):
        raise HTTPException(409, f"Team key {key} already exists")
    team = m.Team(key=key, name=body.name)
    for pos, (name, typ, color) in enumerate(DEFAULT_STATUSES):
        team.statuses.append(m.Status(name=name, type=typ, position=pos, color=color))
    db.add(team)
    db.commit()
    return team


@router.get("/users", response_model=list[s.UserOut])
def list_users(db: Session = Depends(get_session)):
    return db.scalars(select(m.User).order_by(m.User.name)).all()


@router.post("/users", response_model=s.UserOut, status_code=201)
def create_user(body: s.UserIn, db: Session = Depends(get_session)):
    if db.scalar(select(m.User).where(m.User.name == body.name)):
        raise HTTPException(409, "User already exists")
    user = m.User(**body.model_dump())
    db.add(user)
    db.commit()
    return user


@router.get("/labels", response_model=list[s.LabelOut])
def list_labels(db: Session = Depends(get_session)):
    return db.scalars(select(m.Label).order_by(m.Label.name)).all()


@router.post("/labels", response_model=s.LabelOut, status_code=201)
def create_label(body: s.LabelIn, db: Session = Depends(get_session)):
    dup = db.scalar(select(m.Label).where(m.Label.name == body.name, m.Label.team_id == body.team_id))
    if dup:
        raise HTTPException(409, "Label already exists")
    label = m.Label(**body.model_dump())
    db.add(label)
    db.commit()
    return label


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(label_id: int, db: Session = Depends(get_session)):
    db.delete(_get(db, m.Label, label_id, "Label"))
    db.commit()
    return Response(status_code=204)


# ---- issues ----------------------------------------------------------------
@router.get("/issues", response_model=list[s.IssueOut])
def list_issues(
    team: str | None = None,
    status_id: int | None = None,
    status_type: str | None = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
    project_id: int | None = None,
    milestone_id: int | None = None,
    cycle_id: int | None = None,
    label_id: int | None = None,
    priority: int | None = Query(default=None, ge=0, le=4),
    parent_id: int | None = None,
    q: str | None = None,
    order_by: str = Query(default="updated", pattern="^(updated|created|priority|number)$"),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_session),
):
    stmt = select(m.Issue).options(
        selectinload(m.Issue.status), selectinload(m.Issue.labels), selectinload(m.Issue.team),
        selectinload(m.Issue.assignee), selectinload(m.Issue.project),
    )
    if team:
        stmt = stmt.where(m.Issue.team_id == _team(db, team).id)
    if status_id is not None:
        stmt = stmt.where(m.Issue.status_id == status_id)
    if status_type:
        stmt = stmt.join(m.Status, m.Issue.status_id == m.Status.id).where(m.Status.type == status_type)
    if unassigned:
        stmt = stmt.where(m.Issue.assignee_id.is_(None))
    elif assignee_id is not None:
        stmt = stmt.where(m.Issue.assignee_id == assignee_id)
    if project_id is not None:
        stmt = stmt.where(m.Issue.project_id == project_id)
    if milestone_id is not None:
        stmt = stmt.where(m.Issue.milestone_id == milestone_id)
    if cycle_id is not None:
        stmt = stmt.where(m.Issue.cycle_id == cycle_id)
    if label_id is not None:
        stmt = stmt.where(m.Issue.labels.any(m.Label.id == label_id))
    if priority is not None:
        stmt = stmt.where(m.Issue.priority == priority)
    if parent_id is not None:
        stmt = stmt.where(m.Issue.parent_id == parent_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(m.Issue.title.ilike(like), m.Issue.description.ilike(like)))
    order = {
        "updated": m.Issue.updated_at.desc(),
        "created": m.Issue.created_at.desc(),
        "number": m.Issue.number.desc(),
        # 0 (no priority) sorts last, like Linear
        "priority": (m.Issue.priority == 0, m.Issue.priority, m.Issue.updated_at.desc()),
    }[order_by]
    stmt = stmt.order_by(*order) if isinstance(order, tuple) else stmt.order_by(order)
    return _issues_out(db, list(db.scalars(stmt.limit(limit))))


@router.post("/issues", response_model=s.IssueDetailOut, status_code=201)
def create_issue(body: s.IssueIn, db: Session = Depends(get_session)):
    team = _team(db, body.team)
    if body.status_id is not None:
        status = _get(db, m.Status, body.status_id, "Status")
    else:
        status = next((x for x in team.statuses if x.type == "backlog"), team.statuses[0])
    if body.assignee_id is not None:
        _get(db, m.User, body.assignee_id, "User")
    if body.project_id is not None:
        _get(db, m.Project, body.project_id, "Project")
    _check_parent(db, None, body.parent_id)

    team.issue_counter += 1
    issue = m.Issue(
        team_id=team.id,
        number=team.issue_counter,
        title=body.title,
        description=body.description,
        status=status,
        priority=body.priority,
        estimate=body.estimate,
        assignee_id=body.assignee_id,
        project_id=body.project_id,
        milestone_id=body.milestone_id,
        cycle_id=body.cycle_id,
        parent_id=body.parent_id,
        due_date=body.due_date,
    )
    _apply_status(issue, status)
    issue.labels = _labels(db, body.label_ids)
    db.add(issue)
    db.commit()
    return _issue_detail(db, issue)


def _issue_detail(db: Session, issue: m.Issue) -> s.IssueDetailOut:
    subs, comments = _counts(db, [issue])
    base = _issue_out(issue, subs, comments, db)
    children = list(db.scalars(select(m.Issue).where(m.Issue.parent_id == issue.id).order_by(m.Issue.number)))
    return s.IssueDetailOut(
        **base.model_dump(),
        comments=[s.CommentOut.model_validate(c) for c in issue.comments],
        sub_issues=_issues_out(db, children),
    )


@router.get("/issues/{ref}", response_model=s.IssueDetailOut)
def get_issue(ref: str, db: Session = Depends(get_session)):
    return _issue_detail(db, _issue(db, ref))


@router.patch("/issues/{ref}", response_model=s.IssueDetailOut)
def update_issue(ref: str, body: s.IssuePatch, db: Session = Depends(get_session)):
    issue = _issue(db, ref)
    data = body.model_dump(exclude_unset=True)
    if data.get("title", "x") is None or data.get("status_id", 0) is None:
        raise HTTPException(422, "title and status_id cannot be null")
    if "status_id" in data:
        _apply_status(issue, _get(db, m.Status, data.pop("status_id"), "Status"))
    if "label_ids" in data:
        issue.labels = _labels(db, data.pop("label_ids") or [])
    if data.get("assignee_id") is not None:
        _get(db, m.User, data["assignee_id"], "User")
    if data.get("project_id") is not None:
        _get(db, m.Project, data["project_id"], "Project")
    if "parent_id" in data:
        _check_parent(db, issue, data["parent_id"])
    for field, value in data.items():
        setattr(issue, field, value)
    db.commit()
    return _issue_detail(db, issue)


@router.delete("/issues/{ref}", status_code=204)
def delete_issue(ref: str, db: Session = Depends(get_session)):
    issue = _issue(db, ref)
    db.delete(issue)
    db.commit()
    return Response(status_code=204)


@router.post("/issues/{ref}/comments", response_model=s.CommentOut, status_code=201)
def add_comment(ref: str, body: s.CommentIn, db: Session = Depends(get_session)):
    issue = _issue(db, ref)
    if body.author_id is not None:
        _get(db, m.User, body.author_id, "User")
    comment = m.Comment(issue_id=issue.id, author_id=body.author_id, body=body.body)
    db.add(comment)
    issue.updated_at = datetime.now(timezone.utc)
    db.commit()
    return comment


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, db: Session = Depends(get_session)):
    db.delete(_get(db, m.Comment, comment_id, "Comment"))
    db.commit()
    return Response(status_code=204)


# ---- projects / milestones / documents ------------------------------------
@router.get("/projects", response_model=list[s.ProjectOut])
def list_projects(team: str | None = None, status: str | None = None, db: Session = Depends(get_session)):
    stmt = select(m.Project).order_by(m.Project.created_at.desc())
    if team:
        stmt = stmt.where(m.Project.team_id == _team(db, team).id)
    if status:
        stmt = stmt.where(m.Project.status == status)
    return [_project_out(db, p) for p in db.scalars(stmt)]


def _project_detail(db: Session, p: m.Project) -> s.ProjectDetailOut:
    return s.ProjectDetailOut(
        **_project_out(db, p).model_dump(),
        milestones=[_milestone_out(db, x) for x in p.milestones],
        documents=[s.DocumentOut.model_validate(d) for d in p.documents],
    )


@router.post("/projects", response_model=s.ProjectDetailOut, status_code=201)
def create_project(body: s.ProjectIn, db: Session = Depends(get_session)):
    _check_project_status(body.status)
    team = _team(db, body.team)
    if body.lead_id is not None:
        _get(db, m.User, body.lead_id, "User")
    project = m.Project(team_id=team.id, **body.model_dump(exclude={"team"}))
    db.add(project)
    db.commit()
    return _project_detail(db, project)


@router.get("/projects/{project_id}", response_model=s.ProjectDetailOut)
def get_project(project_id: int, db: Session = Depends(get_session)):
    return _project_detail(db, _get(db, m.Project, project_id, "Project"))


@router.patch("/projects/{project_id}", response_model=s.ProjectDetailOut)
def update_project(project_id: int, body: s.ProjectPatch, db: Session = Depends(get_session)):
    project = _get(db, m.Project, project_id, "Project")
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        _check_project_status(data["status"])
    if data.get("lead_id") is not None:
        _get(db, m.User, data["lead_id"], "User")
    for field, value in data.items():
        setattr(project, field, value)
    db.commit()
    return _project_detail(db, project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_session)):
    db.delete(_get(db, m.Project, project_id, "Project"))
    db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/milestones", response_model=s.MilestoneOut, status_code=201)
def create_milestone(project_id: int, body: s.MilestoneIn, db: Session = Depends(get_session)):
    _get(db, m.Project, project_id, "Project")
    ms = m.Milestone(project_id=project_id, **body.model_dump())
    db.add(ms)
    db.commit()
    return _milestone_out(db, ms)


@router.delete("/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: int, db: Session = Depends(get_session)):
    db.delete(_get(db, m.Milestone, milestone_id, "Milestone"))
    db.commit()
    return Response(status_code=204)


@router.get("/documents", response_model=list[s.DocumentOut])
def list_documents(project_id: int | None = None, db: Session = Depends(get_session)):
    stmt = select(m.Document).order_by(m.Document.updated_at.desc())
    if project_id is not None:
        stmt = stmt.where(m.Document.project_id == project_id)
    return db.scalars(stmt).all()


@router.post("/documents", response_model=s.DocumentOut, status_code=201)
def create_document(body: s.DocumentIn, db: Session = Depends(get_session)):
    if body.project_id is not None:
        _get(db, m.Project, body.project_id, "Project")
    doc = m.Document(**body.model_dump())
    db.add(doc)
    db.commit()
    return doc


@router.get("/documents/{doc_id}", response_model=s.DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_session)):
    return _get(db, m.Document, doc_id, "Document")


@router.patch("/documents/{doc_id}", response_model=s.DocumentOut)
def update_document(doc_id: int, body: s.DocumentPatch, db: Session = Depends(get_session)):
    doc = _get(db, m.Document, doc_id, "Document")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(doc, field, value)
    db.commit()
    return doc


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_session)):
    db.delete(_get(db, m.Document, doc_id, "Document"))
    db.commit()
    return Response(status_code=204)


# ---- cycles ----------------------------------------------------------------
@router.get("/cycles", response_model=list[s.CycleOut])
def list_cycles(team: str | None = None, db: Session = Depends(get_session)):
    stmt = select(m.Cycle).order_by(m.Cycle.number.desc())
    if team:
        stmt = stmt.where(m.Cycle.team_id == _team(db, team).id)
    return db.scalars(stmt).all()


@router.post("/cycles", response_model=s.CycleOut, status_code=201)
def create_cycle(body: s.CycleIn, db: Session = Depends(get_session)):
    if body.ends_at < body.starts_at:
        raise HTTPException(422, "ends_at must not be before starts_at")
    team = _team(db, body.team)
    number = (db.scalar(select(func.max(m.Cycle.number)).where(m.Cycle.team_id == team.id)) or 0) + 1
    cycle = m.Cycle(team_id=team.id, number=number, name=body.name, starts_at=body.starts_at, ends_at=body.ends_at)
    db.add(cycle)
    db.commit()
    return cycle
