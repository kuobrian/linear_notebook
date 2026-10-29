from conftest import status_id


def make_issue(client, **kw):
    body = {"team": "ENG", "title": "Something", **kw}
    r = client.post("/api/issues", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_team_gets_default_statuses_and_uppercase_key(team):
    assert team["key"] == "ENG"
    assert [s["type"] for s in team["statuses"]] == ["backlog", "unstarted", "started", "completed", "canceled"]


def test_duplicate_team_key_conflicts(client, team):
    r = client.post("/api/teams", json={"key": "ENG", "name": "Again"})
    assert r.status_code == 409


def test_issue_numbers_increment_and_lookup_by_identifier(client, team):
    a, b = make_issue(client, title="A"), make_issue(client, title="B")
    assert (a["identifier"], b["identifier"]) == ("ENG-1", "ENG-2")
    assert a["status"]["type"] == "backlog"
    assert client.get("/api/issues/eng-2").json()["title"] == "B"
    assert client.get(f"/api/issues/{a['id']}").json()["identifier"] == "ENG-1"
    assert client.get("/api/issues/ENG-99").status_code == 404
    assert client.get("/api/issues/nonsense").status_code == 404


def test_completing_and_reopening_sets_timestamps(client, team):
    issue = make_issue(client)
    done = client.patch("/api/issues/ENG-1", json={"status_id": status_id(team, "completed")}).json()
    assert done["completed_at"] and not done["canceled_at"]
    canceled = client.patch("/api/issues/ENG-1", json={"status_id": status_id(team, "canceled")}).json()
    assert canceled["canceled_at"] and not canceled["completed_at"]
    reopened = client.patch("/api/issues/ENG-1", json={"status_id": status_id(team, "started")}).json()
    assert not reopened["completed_at"] and not reopened["canceled_at"]
    assert issue["number"] == 1


def test_status_from_other_team_rejected(client, team):
    other = client.post("/api/teams", json={"key": "OPS", "name": "Ops"}).json()
    make_issue(client)
    r = client.patch("/api/issues/ENG-1", json={"status_id": status_id(other, "started")})
    assert r.status_code == 422


def test_patch_null_clears_assignee_but_omitted_fields_are_kept(client, team):
    user = client.post("/api/users", json={"name": "Sam"}).json()
    make_issue(client, assignee_id=user["id"], priority=2)
    cleared = client.patch("/api/issues/ENG-1", json={"assignee_id": None}).json()
    assert cleared["assignee"] is None
    assert cleared["priority"] == 2
    assert client.patch("/api/issues/ENG-1", json={"title": None}).status_code == 422


def test_labels_assign_and_filter(client, team):
    bug = client.post("/api/labels", json={"name": "Bug"}).json()
    assert client.post("/api/labels", json={"name": "Bug"}).status_code == 409
    make_issue(client, title="has label", label_ids=[bug["id"]])
    make_issue(client, title="plain")
    found = client.get("/api/issues", params={"label_id": bug["id"]}).json()
    assert [i["title"] for i in found] == ["has label"]
    assert client.post("/api/issues", json={"team": "ENG", "title": "x", "label_ids": [999]}).status_code == 422


def test_filters_search_and_priority_ordering(client, team):
    make_issue(client, title="low", priority=4)
    make_issue(client, title="none", priority=0)
    make_issue(client, title="urgent bug", priority=1)
    ordered = client.get("/api/issues", params={"order_by": "priority"}).json()
    assert [i["title"] for i in ordered] == ["urgent bug", "low", "none"]
    assert [i["title"] for i in client.get("/api/issues", params={"q": "BUG"}).json()] == ["urgent bug"]
    assert len(client.get("/api/issues", params={"priority": 4}).json()) == 1
    assert len(client.get("/api/issues", params={"unassigned": True}).json()) == 3
    assert len(client.get("/api/issues", params={"status_type": "started"}).json()) == 0
    assert client.get("/api/issues", params={"team": "NOPE"}).status_code == 404


def test_sub_issues_and_cycle_protection(client, team):
    parent = make_issue(client, title="parent")
    child = make_issue(client, title="child", parent_id=parent["id"])
    detail = client.get("/api/issues/ENG-1").json()
    assert detail["sub_issue_count"] == 1
    assert [s["identifier"] for s in detail["sub_issues"]] == ["ENG-2"]
    assert child["parent_identifier"] == "ENG-1"
    # making the parent a child of its own child must fail
    assert client.patch("/api/issues/ENG-1", json={"parent_id": child["id"]}).status_code == 422
    assert client.patch("/api/issues/ENG-1", json={"parent_id": parent["id"]}).status_code == 422


def test_comments(client, team):
    user = client.post("/api/users", json={"name": "Sam"}).json()
    make_issue(client)
    c = client.post("/api/issues/ENG-1/comments", json={"body": "hello", "author_id": user["id"]})
    assert c.status_code == 201
    detail = client.get("/api/issues/ENG-1").json()
    assert detail["comment_count"] == 1 and detail["comments"][0]["author"]["name"] == "Sam"
    assert client.post("/api/issues/ENG-1/comments", json={"body": ""}).status_code == 422
    assert client.delete(f"/api/comments/{c.json()['id']}").status_code == 204
    assert client.get("/api/issues/ENG-1").json()["comment_count"] == 0


def test_delete_issue(client, team):
    make_issue(client)
    assert client.delete("/api/issues/ENG-1").status_code == 204
    assert client.get("/api/issues/ENG-1").status_code == 404
    # numbers are never reused
    assert make_issue(client)["identifier"] == "ENG-2"


def test_project_progress_and_milestones(client, team):
    project = client.post("/api/projects", json={"team": "ENG", "name": "Launch"}).json()
    pid = project["id"]
    assert project["progress"] == {"total": 0, "completed": 0, "started": 0, "percent": 0}
    ms = client.post(f"/api/projects/{pid}/milestones", json={"name": "Beta"}).json()
    make_issue(client, project_id=pid, milestone_id=ms["id"], status_id=status_id(team, "completed"))
    make_issue(client, project_id=pid, milestone_id=ms["id"], status_id=status_id(team, "started"))
    make_issue(client, project_id=pid, status_id=status_id(team, "canceled"))  # not counted
    got = client.get(f"/api/projects/{pid}").json()
    assert got["progress"] == {"total": 2, "completed": 1, "started": 1, "percent": 50}
    assert got["milestones"][0]["issue_count"] == 2 and got["milestones"][0]["done_count"] == 1
    assert client.patch(f"/api/projects/{pid}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"status": "started"}).json()["status"] == "started"


def test_deleting_project_keeps_issues(client, team):
    pid = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()["id"]
    make_issue(client, project_id=pid)
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    issue = client.get("/api/issues/ENG-1").json()
    assert issue["project_id"] is None


def test_documents(client, team):
    pid = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()["id"]
    doc = client.post("/api/documents", json={"title": "Spec", "project_id": pid}).json()
    client.patch(f"/api/documents/{doc['id']}", json={"content": "# hi"})
    assert client.get(f"/api/documents/{doc['id']}").json()["content"] == "# hi"
    assert [d["title"] for d in client.get(f"/api/projects/{pid}").json()["documents"]] == ["Spec"]
    assert client.post("/api/documents", json={"title": "x", "project_id": 99}).status_code == 404


def test_cycles_number_per_team(client, team):
    body = {"team": "ENG", "starts_at": "2026-01-01", "ends_at": "2026-01-14"}
    assert client.post("/api/cycles", json=body).json()["number"] == 1
    assert client.post("/api/cycles", json=body).json()["number"] == 2
    bad = {**body, "ends_at": "2025-12-01"}
    assert client.post("/api/cycles", json=bad).status_code == 422


def test_meta_and_index(client, team):
    meta = client.get("/api/meta").json()
    assert meta["teams"][0]["key"] == "ENG" and meta["priorities"][1]["name"] == "Urgent"
    index = client.get("/")
    assert index.status_code == 200 and "Local Linear" in index.text
    assert client.get("/api/nope").status_code == 404
