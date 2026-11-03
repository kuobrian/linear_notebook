from conftest import status_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from local_linear import models as m
from local_linear.db import make_engine
from local_linear.migrate import CopyError, copy_database, table_counts

import pytest


def target_url(tmp_path, name="target.db"):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def make_issues(client, team):
    """Two issues where the first one is re-parented to the newer second one, plus a comment and a label."""
    todo = status_id(team, "unstarted")
    label = client.post("/api/labels", json={"name": "Bug"}).json()
    a = client.post("/api/issues", json={"team": "eng", "title": "A", "status_id": todo, "label_ids": [label["id"]]}).json()
    b = client.post("/api/issues", json={"team": "eng", "title": "B", "status_id": todo}).json()
    assert client.patch(f"/api/issues/{a['id']}", json={"parent_id": b["id"]}).status_code == 200
    assert client.post(f"/api/issues/{a['id']}/comments", json={"body": "hello"}).status_code == 201
    return a, b


def test_copy_keeps_ids_parents_and_counts(client, team, tmp_path):
    a, b = make_issues(client, team)
    target = make_engine(target_url(tmp_path))

    copied = copy_database(_source(client), target)

    assert copied == table_counts(target)
    assert copied["issues"] == 2 and copied["comments"] == 1 and copied["issue_labels"] == 1
    with Session(target) as db:
        issue = db.get(m.Issue, a["id"])
        assert issue.parent_id == b["id"] and issue.number == a["number"]
        assert db.get(m.Team, team["id"]).issue_counter == 2
        assert db.scalar(select(m.Comment.body)) == "hello"


def _source(client):
    from local_linear.db import get_session
    from local_linear.main import app

    return next(app.dependency_overrides[get_session]()).get_bind()


def test_copy_refuses_a_target_that_already_has_data(client, team, tmp_path):
    source = _source(client)
    target = make_engine(target_url(tmp_path))
    copy_database(source, target)
    with pytest.raises(CopyError, match="not empty"):
        copy_database(source, target)
    assert table_counts(target)["teams"] == 1  # the first copy is untouched


def test_copy_endpoint(client, team, tmp_path):
    make_issues(client, team)
    url = target_url(tmp_path)

    r = client.post("/api/database/copy", json={"url": url})
    assert r.status_code == 200, r.text
    assert r.json()["copied"]["issues"] == 2
    assert table_counts(make_engine(url))["issues"] == 2

    assert client.post("/api/database/copy", json={"url": url}).status_code == 409  # now not empty


@pytest.mark.parametrize("url", ["mysql://u:p@h/db", "not a url", "   "])
def test_copy_endpoint_rejects_bad_urls(client, url):
    assert client.post("/api/database/copy", json={"url": url}).status_code in (422,)


def test_copy_endpoint_reports_an_unreachable_server_without_the_password(client):
    r = client.post("/api/database/copy", json={"url": "postgresql://u:secret-pw@127.0.0.1:1/x"})
    assert r.status_code == 400
    assert "secret-pw" not in r.text


def test_database_info_hides_the_password(client, team):
    info = client.get("/api/database").json()
    assert info["kind"] in ("sqlite", "postgresql")
    assert info["counts"]["teams"] == 1
    assert "***" in info["location"] or "@" not in info["location"]
