from datetime import datetime

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


def test_cycle_edit_and_delete_keep_the_issues(client, team):
    cycle = client.post("/api/cycles", json={"team": "ENG", "starts_at": "2026-01-01", "ends_at": "2026-01-14"}).json()
    issue = client.post("/api/issues", json={"team": "ENG", "title": "in cycle", "cycle_id": cycle["id"]}).json()

    r = client.patch(f"/api/cycles/{cycle['id']}", json={"name": "Sprint", "ends_at": "2026-01-21"})
    assert r.status_code == 200 and r.json()["name"] == "Sprint" and r.json()["ends_at"] == "2026-01-21"
    assert client.patch(f"/api/cycles/{cycle['id']}", json={"name": None}).json()["name"] is None
    for bad in ({"ends_at": "2025-12-31"}, {"starts_at": "2026-02-01"}, {"starts_at": None}):
        assert client.patch(f"/api/cycles/{cycle['id']}", json=bad).status_code == 422
    assert client.patch("/api/cycles/9999", json={"name": "x"}).status_code == 404

    assert client.delete(f"/api/cycles/{cycle['id']}").status_code == 204
    assert client.delete(f"/api/cycles/{cycle['id']}").status_code == 404
    assert client.get("/api/issues/" + issue["identifier"]).json()["cycle_id"] is None


def test_meta_and_index(client, team):
    meta = client.get("/api/meta").json()
    assert meta["teams"][0]["key"] == "ENG" and meta["priorities"][1]["name"] == "Urgent"
    index = client.get("/")
    assert index.status_code == 200 and "Local Linear" in index.text
    assert client.get("/api/nope").status_code == 404


def test_search_matches_issue_identifier(client, team):
    client.post("/api/teams", json={"key": "OPS", "name": "Ops"})
    pid = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()["id"]
    make_issue(client, title="first", project_id=pid)                      # ENG-1
    make_issue(client, title="second")                                     # ENG-2
    client.post("/api/issues", json={"team": "OPS", "title": "ops first"})  # OPS-1

    ids = lambda **params: [i["identifier"] for i in client.get("/api/issues", params=params).json()]  # noqa: E731
    assert ids(q="ENG-2") == ["ENG-2"]
    assert ids(q="eng-2") == ["ENG-2"]            # case-insensitive
    assert ids(q="  ENG-1 ") == ["ENG-1"]         # surrounding spaces are ignored
    assert ids(q="OPS-1") == ["OPS-1"]            # same number in another team is not confused
    assert ids(q="ENG-99") == []
    assert ids(q="ENG-") == [] and ids(q="ENG-1x") == []   # only a complete id matches by id
    assert ids(q="ENG-1", project_id=pid) == ["ENG-1"]      # works together with other filters
    assert ids(q="ENG-2", project_id=pid) == []
    assert sorted(ids(q="first")) == ["ENG-1", "OPS-1"]     # text search is unchanged


def test_search_by_id_also_finds_text_mentions(client, team):
    make_issue(client, title="blocks ENG-2 from shipping")  # ENG-1, mentions ENG-2
    make_issue(client, title="plain")                       # ENG-2
    assert sorted(i["identifier"] for i in client.get("/api/issues", params={"q": "ENG-2"}).json()) == ["ENG-1", "ENG-2"]


def test_timestamps_carry_a_time_zone_when_read_back(client, team):
    make_issue(client)
    client.post("/api/issues/ENG-1/comments", json={"body": "x"})
    detail = client.get("/api/issues/ENG-1").json()  # read from the database, not the create response
    for stamp in (detail["created_at"], detail["updated_at"], detail["comments"][0]["created_at"]):
        assert datetime.fromisoformat(stamp).tzinfo is not None  # a bare time would be read as local time


def test_bad_input_is_rejected_instead_of_crashing(client, team):
    make_issue(client)
    pid = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()["id"]
    # null clears optional fields, but not NOT NULL ones
    for body in ({"title": None}, {"description": None}, {"status_id": None}, {"priority": None}):
        assert client.patch("/api/issues/ENG-1", json=body).status_code == 422, body
    for body in ({"name": None}, {"summary": None}, {"description": None}, {"color": None}, {"priority": None}):
        assert client.patch(f"/api/projects/{pid}", json=body).status_code == 422, body
    # ids that do not exist, or are too big for the database
    for body in ({"milestone_id": 9999}, {"cycle_id": 9999}, {"project_id": 10**20}):
        assert client.patch("/api/issues/ENG-1", json=body).status_code == 404, body
        assert client.post("/api/issues", json={"team": "ENG", "title": "x", **body}).status_code == 404, body
    assert client.get(f"/api/projects/{10**20}").status_code == 404
    # text longer than its column (PostgreSQL refuses it; SQLite would silently keep it)
    assert client.patch(f"/api/projects/{pid}", json={"summary": "x" * 301}).status_code == 422
    assert client.post("/api/projects", json={"team": "ENG", "name": "P", "color": "x" * 21}).status_code == 422
    assert client.post("/api/labels", json={"name": "L", "color": "x" * 21}).status_code == 422
    # an issue number too long to exist is simply not found
    assert client.get("/api/issues", params={"q": "ENG-99999999999999999999"}).json() == []
    assert client.get("/api/issues/ENG-99999999999999999999").status_code == 404
    assert client.get("/api/issues/99999999999999999999").status_code == 404
    assert client.get("/api/issues/ENG-1").json()["title"] == "Something"  # nothing above changed it


def test_static_files_are_revalidated_not_cached_blindly(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
    # a conditional request is answered with 304, so revalidation costs no re-download
    assert client.get("/static/app.js", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_delete_issue_in_every_kind_of_situation(client, team):
    user = client.post("/api/users", json={"name": "Sam"}).json()
    label = client.post("/api/labels", json={"name": "Bug"}).json()
    project = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()
    milestone = client.post(f"/api/projects/{project['id']}/milestones", json={"name": "M"}).json()
    cycle = client.post("/api/cycles", json={"team": "ENG", "starts_at": "2026-01-01", "ends_at": "2026-01-14"}).json()

    loaded = make_issue(
        client, title="loaded", label_ids=[label["id"]], assignee_id=user["id"], project_id=project["id"],
        milestone_id=milestone["id"], cycle_id=cycle["id"], status_id=status_id(team, "completed"),
    )
    client.post(f"/api/issues/{loaded['identifier']}/comments", json={"body": "x"})
    parent = make_issue(client, title="parent")
    child = make_issue(client, title="child", parent_id=parent["id"])

    assert client.delete(f"/api/issues/{loaded['identifier']}").status_code == 204
    assert client.delete(f"/api/issues/{parent['identifier']}").status_code == 204
    # the sub-issue survives its parent and becomes a top-level issue
    assert client.get(f"/api/issues/{child['identifier']}").json()["parent_id"] is None
    assert client.delete(f"/api/issues/{child['identifier']}").status_code == 204
    assert client.get("/api/issues").json() == []
    # the project, label, user and milestone the issue pointed at are untouched
    assert client.get(f"/api/projects/{project['id']}").json()["milestones"][0]["issue_count"] == 0
    assert [x["name"] for x in client.get("/api/labels").json()] == ["Bug"]
    assert [u["name"] for u in client.get("/api/users").json()] == ["Sam"]


def test_huge_or_invalid_ids_are_rejected_instead_of_crashing(client, team):
    make_issue(client)
    for value in (0, -5, 2**31, 10**30):
        for param in ("status_id", "assignee_id", "project_id", "milestone_id", "cycle_id", "label_id", "parent_id"):
            assert client.get(f"/api/issues?{param}={value}").status_code == 422, (param, value)
        assert client.patch("/api/issues/ENG-1", json={"label_ids": [value]}).status_code == 422, value
        assert client.post("/api/issues", json={"team": "ENG", "title": "x", "label_ids": [value]}).status_code == 422
        assert client.post("/api/labels", json={"name": "L", "team_id": value}).status_code == 404, value
    assert client.patch("/api/issues/ENG-1", json={"label_ids": list(range(1, 300))}).status_code == 422


def test_odd_digits_in_an_issue_reference_are_a_404_not_a_crash(client, team):
    make_issue(client)
    for ref in ("²", "٣", "ENG-٣", "１"):  # superscript, Arabic-Indic and full-width digits
        assert client.get(f"/api/issues/{ref}").status_code == 404, ref


def test_document_filter_rejects_huge_project_ids(client, team):
    for value in (0, 2**31, 10**30):
        assert client.get(f"/api/documents?project_id={value}").status_code == 422, value


def test_search_treats_percent_and_underscore_as_plain_text(client, team):
    for title in ("100% sure", "a_b", "axb", "plain"):
        make_issue(client, title=title)

    def found(q):
        return sorted(i["title"] for i in client.get("/api/issues", params={"q": q}).json())

    assert found("%") == ["100% sure"]
    assert found("_") == ["a_b"]
    assert found("a_b") == ["a_b"]  # not "axb"
    assert found("PLAIN") == ["plain"]  # still case-insensitive


def test_setting_the_same_status_again_keeps_the_completion_time(client, team):
    make_issue(client)
    done = status_id(team, "completed")
    first = client.patch("/api/issues/ENG-1", json={"status_id": done}).json()["completed_at"]
    again = client.patch("/api/issues/ENG-1", json={"status_id": done, "title": "Renamed"}).json()
    assert again["completed_at"] == first and again["title"] == "Renamed"
    canceled = status_id(team, "canceled")
    first = client.patch("/api/issues/ENG-1", json={"status_id": canceled}).json()["canceled_at"]
    assert client.patch("/api/issues/ENG-1", json={"status_id": canceled}).json()["canceled_at"] == first


def test_listing_projects_uses_a_fixed_number_of_queries(client, team):
    from sqlalchemy import event

    from local_linear.db import get_session
    from local_linear.main import app

    engine = next(app.dependency_overrides[get_session]()).get_bind()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))

    lead = client.post("/api/users", json={"name": "Sam"}).json()

    def queries_for(total):
        while len(client.get("/api/projects").json()) < total:
            name = f"P{len(client.get('/api/projects').json())}"
            p = client.post("/api/projects", json={"team": "ENG", "name": name, "lead_id": lead["id"]}).json()
            make_issue(client, project_id=p["id"])
        statements.clear()
        assert client.get("/api/projects").status_code == 200
        return len(statements)

    assert queries_for(2) == queries_for(6)  # in this order: the project count only grows


def test_estimate_must_fit_the_database_column(client, team):
    # SQLite would store 2**40, but PostgreSQL cannot, which would break "Copy data" later
    for bad in (-1, 2**31, 10**30):
        assert client.post("/api/issues", json={"team": "ENG", "title": "x", "estimate": bad}).status_code == 422, bad
    make_issue(client)
    assert client.patch("/api/issues/ENG-1", json={"estimate": 2**31}).status_code == 422
    assert client.patch("/api/issues/ENG-1", json={"estimate": 2**31 - 1}).status_code == 200



# ---- coverage gaps (KUO-12): filters, deletes, lists, conflicts ------------------------------
def titles(client, **params):
    r = client.get("/api/issues", params=params)
    assert r.status_code == 200, r.text
    return {i["title"] for i in r.json()}


def test_issue_filters_return_exactly_the_matching_issues(client, team):
    ann = client.post("/api/users", json={"name": "Ann"}).json()
    project = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()
    ms = client.post(f"/api/projects/{project['id']}/milestones", json={"name": "M1"}).json()
    cycle = client.post("/api/cycles", json={"team": "ENG", "starts_at": "2026-01-01", "ends_at": "2026-01-14"}).json()
    parent = make_issue(client, title="parent")
    make_issue(client, title="child", parent_id=parent["id"])
    make_issue(client, title="assigned", assignee_id=ann["id"])
    make_issue(client, title="milestoned", project_id=project["id"], milestone_id=ms["id"])
    make_issue(client, title="cycled", cycle_id=cycle["id"])
    done = make_issue(client, title="done", status_id=status_id(team, "completed"))

    assert titles(client, parent_id=parent["id"]) == {"child"}
    assert titles(client, assignee_id=ann["id"]) == {"assigned"}
    assert titles(client, milestone_id=ms["id"]) == {"milestoned"}
    assert titles(client, cycle_id=cycle["id"]) == {"cycled"}
    assert titles(client, status_id=done["status"]["id"]) == {"done"}
    assert titles(client, status_id=done["status"]["id"], cycle_id=cycle["id"]) == set()  # filters combine
    assert titles(client, parent_id=999) == set()  # a valid but unused id matches nothing


def test_deleting_labels_milestones_and_documents(client, team):
    label = client.post("/api/labels", json={"name": "Temp"}).json()
    issue = make_issue(client, label_ids=[label["id"]])
    assert client.delete(f"/api/labels/{label['id']}").status_code == 204
    assert client.get(f"/api/issues/{issue['identifier']}").json()["labels"] == []
    assert client.delete(f"/api/labels/{label['id']}").status_code == 404

    project = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()
    ms = client.post(f"/api/projects/{project['id']}/milestones", json={"name": "M1"}).json()
    assert client.delete(f"/api/milestones/{ms['id']}").status_code == 204
    assert client.delete(f"/api/milestones/{ms['id']}").status_code == 404
    assert client.get(f"/api/projects/{project['id']}").json()["milestones"] == []

    doc = client.post("/api/documents", json={"title": "D", "project_id": project["id"]}).json()
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404


def test_document_list_filter_and_partial_update(client, team):
    project = client.post("/api/projects", json={"team": "ENG", "name": "P"}).json()
    inside = client.post("/api/documents", json={"title": "in", "content": "body", "project_id": project["id"]}).json()
    client.post("/api/documents", json={"title": "loose"})
    assert {d["title"] for d in client.get("/api/documents").json()} == {"in", "loose"}
    assert [d["title"] for d in client.get("/api/documents", params={"project_id": project["id"]}).json()] == ["in"]
    assert client.post("/api/documents", json={"title": "x", "project_id": 999}).status_code == 404

    url = f"/api/documents/{inside['id']}"
    assert client.patch(url, json={"title": "renamed"}).json()["content"] == "body"  # content untouched
    assert client.patch(url, json={"content": "new"}).json()["title"] == "renamed"  # title untouched
    assert client.patch(url, json={"title": None, "content": None}).json()["content"] == "new"  # nulls are ignored
    assert client.patch("/api/documents/999", json={"title": "x"}).status_code == 404


def test_cycle_list_and_team_filter(client, team):
    client.post("/api/teams", json={"key": "OPS", "name": "Ops"})
    body = {"starts_at": "2026-01-01", "ends_at": "2026-01-14"}
    client.post("/api/cycles", json={**body, "team": "ENG"})
    client.post("/api/cycles", json={**body, "team": "ENG"})
    client.post("/api/cycles", json={**body, "team": "OPS"})
    assert len(client.get("/api/cycles").json()) == 3
    eng = client.get("/api/cycles", params={"team": "eng"}).json()
    assert [c["number"] for c in eng] == [2, 1]  # newest first
    assert len(client.get("/api/cycles", params={"team": "OPS"}).json()) == 1
    assert client.get("/api/cycles", params={"team": "NOPE"}).status_code == 404


def test_project_status_filter(client, team):
    client.post("/api/projects", json={"team": "ENG", "name": "A", "status": "started"})
    client.post("/api/projects", json={"team": "ENG", "name": "B", "status": "paused"})

    def names(**params):
        return {x["name"] for x in client.get("/api/projects", params=params).json()}

    assert names(status="started") == {"A"}
    assert names(status="paused") == {"B"}
    assert names(status="completed") == set()
    assert names() == {"A", "B"}


def test_duplicate_user_conflicts(client):
    assert client.post("/api/users", json={"name": "Ann"}).status_code == 201
    r = client.post("/api/users", json={"name": "Ann"})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]


def test_copying_into_the_database_in_use_is_refused(client, team):
    from conftest import TEST_DB

    r = client.post("/api/database/copy", json={"url": TEST_DB or "sqlite://"})
    assert r.status_code == 409 and "already using" in r.json()["detail"]
