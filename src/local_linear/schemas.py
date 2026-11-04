from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, computed_field

from . import markdown

# A database id: positive and within a 32-bit column, so a huge number is a 422, not a driver error.
Id = Annotated[int, Field(ge=1, le=2**31 - 1)]


def _sane_date(d: date) -> date:
    if not date(2000, 1, 1) <= d <= date(2100, 12, 31):
        raise ValueError("date must be between 2000-01-01 and 2100-12-31")
    return d


# A planning date (cycle, project, milestone): 0001-01-01 or 9999-12-31 is a typo, not a plan.
PlanDate = Annotated[date, AfterValidator(_sane_date)]


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

    @computed_field
    @property
    def body_html(self) -> str:
        return markdown.render(self.body)


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

    @computed_field
    @property
    def description_html(self) -> str:
        return markdown.render(self.description)


class DocumentOut(ORM):
    id: int
    project_id: int | None
    title: str
    content: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def content_html(self) -> str:
        return markdown.render(self.content)


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

    @computed_field
    @property
    def description_html(self) -> str:
        return markdown.render(self.description)


class MarkdownIn(BaseModel):
    text: str = Field(max_length=200_000)


class MarkdownOut(BaseModel):
    html: str


# ---- input -----------------------------------------------------------------
class TeamIn(BaseModel):
    key: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9]*$")
    name: str = Field(min_length=1, max_length=100)


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200)


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str = Field(default="#5e6ad2", max_length=20)
    team_id: int | None = None


class IssueIn(BaseModel):
    team: str = Field(description="team key, e.g. KUO")
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    status_id: int | None = None
    priority: int = Field(default=0, ge=0, le=4)
    estimate: int | None = Field(default=None, ge=0, le=2**31 - 1)
    assignee_id: int | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    cycle_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    label_ids: list[Id] = Field(default=[], max_length=200)


class IssuePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status_id: int | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    estimate: int | None = Field(default=None, ge=0, le=2**31 - 1)
    assignee_id: int | None = None
    project_id: int | None = None
    milestone_id: int | None = None
    cycle_id: int | None = None
    parent_id: int | None = None
    due_date: date | None = None
    label_ids: list[Id] | None = Field(default=None, max_length=200)


class CommentIn(BaseModel):
    body: str = Field(min_length=1)
    author_id: int | None = None


class ProjectIn(BaseModel):
    team: str
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=300)
    description: str = ""
    status: str = "planned"
    priority: int = Field(default=0, ge=0, le=4)
    color: str = Field(default="#4cb782", max_length=20)
    lead_id: int | None = None
    start_date: PlanDate | None = None
    target_date: PlanDate | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=300)
    description: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    color: str | None = Field(default=None, max_length=20)
    lead_id: int | None = None
    start_date: PlanDate | None = None
    target_date: PlanDate | None = None


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_date: PlanDate | None = None


class CycleIn(BaseModel):
    team: str
    name: str | None = Field(default=None, max_length=100)
    starts_at: PlanDate
    ends_at: PlanDate


class CyclePatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    starts_at: PlanDate | None = None
    ends_at: PlanDate | None = None


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    project_id: int | None = None


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = None


class DatabaseCopyIn(BaseModel):
    url: str = Field(min_length=1, max_length=500, description="URL of an empty target database")
