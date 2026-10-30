"""End-to-end: run `local-linear-mcp --transport http` as a real process and talk to it by URL."""

import asyncio
import json
import socket
import sqlite3
import subprocess
import sys
import time

import pytest
from mcp.client import Client


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def http_server(tmp_path):
    db = tmp_path / "http.db"
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "local_linear.mcp_server", "--transport", "http", "--port", str(port)],
        env={**__import__("os").environ, "LOCAL_LINEAR_DB": f"sqlite:///{db.as_posix()}"},
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
