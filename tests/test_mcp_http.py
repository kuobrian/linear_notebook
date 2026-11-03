"""End-to-end: run `local-linear-mcp --transport http` as a real process and talk to it by URL."""

import asyncio
import json
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from mcp.client import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(params=[""], ids=["open"])
def http_server(tmp_path, request):
    db = tmp_path / "http.db"
    port = _free_port()
    env = {**__import__("os").environ, "LOCAL_LINEAR_DB": f"sqlite:///{db.as_posix()}"}
    env.pop("LOCAL_LINEAR_TOKEN", None)
    if request.param:
        env["LOCAL_LINEAR_TOKEN"] = request.param
    proc = subprocess.Popen(
        [sys.executable, "-m", "local_linear.mcp_server", "--transport", "http", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited: {proc.stderr.read().decode()}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not start")
        yield f"http://127.0.0.1:{port}/mcp", db
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_create_project_over_http(http_server):
    url, db = http_server

    async def run():
        async with Client(url) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert "create_project" in tools
            bad = await client.call_tool("create_project", {"team": "ENG", "name": "x"})
            assert bad.is_error and "Team 'ENG' not found" in bad.content[0].text
            await client.call_tool("create_team", {"key": "ENG", "name": "Engineering"})
            ok = await client.call_tool(
                "create_project", {"team": "ENG", "name": "Over HTTP", "status": "started", "priority": 2}
            )
            return json.loads(ok.content[0].text)

    project = asyncio.run(run())
    assert project["name"] == "Over HTTP" and project["status"] == "started"
    rows = sqlite3.connect(db).execute("select name, status, priority from projects").fetchall()
    assert rows == [("Over HTTP", "started", 2)]


@pytest.mark.parametrize("http_server", ["s3cret"], indirect=True)
def test_token_is_enforced_over_http(http_server):
    url, _ = http_server

    async def run():
        http = create_mcp_http_client(headers={"Authorization": "Bearer s3cret"})
        async with Client(streamable_http_client(url, http_client=http)) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert "create_project" in asyncio.run(run())
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        assert httpx.post(url, json={}, headers=headers).status_code == 401
