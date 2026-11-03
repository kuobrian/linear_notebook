import pytest
from fastapi.testclient import TestClient

from local_linear import mcp_server
from local_linear.hosts import host_allowed


@pytest.mark.parametrize("host, status", [
    ("127.0.0.1:8000", 200), ("localhost", 200), ("LOCALHOST:8000", 200), ("[::1]:8000", 200),
    ("evil.example", 421), ("evil.example:8000", 421), ("127.0.0.1.evil.example", 421), ("localhost.evil.example:8000", 421),
])
def test_web_app_only_answers_to_local_host_names(client, host, status):
    assert client.get("/api/teams", headers={"Host": host}).status_code == status


def test_extra_hosts_can_be_allowed(client, monkeypatch):
    assert client.get("/api/teams", headers={"Host": "nas.lan:8000"}).status_code == 421
    monkeypatch.setenv("LOCAL_LINEAR_ALLOWED_HOSTS", "nas.lan")
    assert client.get("/api/teams", headers={"Host": "nas.lan:8000"}).status_code == 200
    assert not host_allowed("evil.example")


def test_the_copy_endpoint_is_not_reachable_through_a_foreign_host(client, tmp_path):
    body = {"url": f"sqlite:///{(tmp_path / 'stolen.db').as_posix()}"}
    assert client.post("/api/database/copy", json=body, headers={"Host": "evil.example"}).status_code == 421
    assert not (tmp_path / "stolen.db").exists()


def test_mcp_http_refuses_foreign_hosts_even_when_bound_to_all_interfaces():
    # the SDK only protects loopback binds by itself, and the Docker image binds 0.0.0.0
    app = mcp_server.mcp.streamable_http_app(host="0.0.0.0", transport_security=mcp_server.transport_security())
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app) as c:
        assert c.post("/mcp", json=init, headers={**headers, "Host": "127.0.0.1:8765"}).status_code == 200
        assert c.post("/mcp", json=init, headers={**headers, "Host": "evil.example"}).status_code == 421
