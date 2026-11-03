def test_no_token_configured_means_no_login(client):
    assert client.get("/api/teams").status_code == 200


def test_token_is_required_for_api_and_copy_endpoint(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LINEAR_TOKEN", "s3cret")
    assert client.get("/api/teams").status_code == 401
    assert client.get("/api/teams", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/teams", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    body = {"url": f"sqlite:///{(tmp_path / 'x.db').as_posix()}"}
    assert client.post("/api/database/copy", json=body).status_code == 401
    assert not (tmp_path / "x.db").exists()


def test_login_sets_a_cookie_that_unlocks_the_app(client, monkeypatch):
    monkeypatch.setenv("LOCAL_LINEAR_TOKEN", "s3cret")
    assert client.get("/login?token=nope", follow_redirects=False).status_code == 401
    assert client.get("/").status_code == 401
    assert client.get("/login?token=s3cret", follow_redirects=False).status_code == 303
    assert client.get("/api/teams").status_code == 200  # cookie jar kept the cookie


def test_copy_can_be_switched_off(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LINEAR_ALLOW_COPY", "0")
    body = {"url": f"sqlite:///{(tmp_path / 'x.db').as_posix()}"}
    assert client.post("/api/database/copy", json=body).status_code == 403
    assert not (tmp_path / "x.db").exists()
