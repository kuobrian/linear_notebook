from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- output ----------------------------------------------------------------
class UserOut(ORM):
    id: int
    name: str
    email: str | None = None


class StatusOut(ORM):
    id: int
    team_id: int
    name: str
    type: str
    position: int
    color: str


class TeamOut(ORM):
    id: int
    key: str
    name: str
    statuses: list[StatusOut] = []


class LabelOut(ORM):
    id: int
    name: str
    color: str
    team_id: int | None = None


class CommentOut(ORM):
    id: int
    issue_id: int
    author: UserOut | None = None
    body: str
    created_at: datetime


class MilestoneOut(ORM):
    id: int
    project_id: int
    name: str
    description: str
    target_date: date | None = None
    issue_count: int = 0
    done_count: int = 0


class CycleOut(ORM):
    id: int
    team_id: int
    number: int
    name: str | None = None
    starts_at: date
    ends_at: date


class IssueOut(BaseModel):
    id: int
    identifier: str
    team_id: int
    number: int
    title: str
    description: str
    status: StatusOut
    priority: int
    priority_name: str
    estimate: int | None
    assignee: UserOut | None
    project_id: int | None
    project_name: str | None
    milestone_id: int | None
    cycle_id: int | None
    parent_id: int | None
    parent_identifier: str | None
    due_date: date | None
    labels: list[LabelOut]
    sub_issue_count: int = 0
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    canceled_at: datetime | None


class IssueDetailOut(IssueOut):
    comments: list[CommentOut] = []
    sub_issues: list[IssueOut] = []


class DocumentOut(ORM):
    id: int
    project_id: int | None
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class ProjectProgress(BaseModel):
    total: int
    completed: int
    started: int
    percent: int


class ProjectOut(BaseModel):
    id: int
    team_id: int
    name: str
    summary: str
    description: str
    status: str
    priority: int
    color: str
    lead: UserOut | None
    start_date: date | None
    target_date: date | None
    progress: ProjectProgress
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    milestones: list[MilestoneOut] = []
    documents: list[DocumentOut] = []


# ---- input -----------------------------------------------------------------
class TeamIn(BaseModel):
    key: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9]*$")
    name: str = Field(min_length=1, max_length=100)


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str | None = None


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str = "#5e6ad2"
    team_id: int | None = None


class IssueIn(BaseModel):
    team: str = Field(description="team key, e.g. KUO")
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    status_id: int | None = None
    priority: int = Field(default=0, ge=0, le=4)
    estimate: int | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    cycle_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    label_ids: list[int] = []


class IssuePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status_id: int | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    estimate: int | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    cycle_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    label_ids: list[int] | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1)
    author_id: int | None = None


class ProjectIn(BaseModel):
    team: str
    name: str = Field(min_length=1, max_length=200)
    summary: str = ""
    description: str = ""
    status: str = "planned"
    priority: int = Field(default=0, ge=0, le=4)
    color: str = "#4cb782"
    lead_id: int | None = None
    start_date: date | None = None
    target_date: date | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    color: str | None = None
    lead_id: int | None = None
    start_date: date | None = None
    target_date: date | None = None


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_date: date | None = None


class CycleIn(BaseModel):
    team: str
    name: str | None = None
    starts_at: date
    ends_at: date


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    project_id: int | None = None


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = None
