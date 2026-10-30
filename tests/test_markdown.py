import re

import pytest
from conftest import status_id  # noqa: F401  (fixtures: client, team)

from local_linear.markdown import render


def test_basic_formatting():
    html = render("# Title\n\n**bold** and *italic* and `code` and ~~gone~~")
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<code>code</code>" in html and "<s>gone</s>" in html


def test_lists_code_blocks_quotes_tables():
    html = render("- a\n- b\n\n1. one\n2. two\n\n> quote\n\n```py\nprint(1)\n```\n\n| h1 | h2 |\n|----|----|\n| x  | y  |")
    assert "<ul>" in html and "<ol>" in html and "<blockquote>" in html
    assert '<pre><code class="language-py">' in html
    assert "<table>" in html and "<th>h1</th>" in html


def test_task_lists_render_read_only_checkboxes():
    html = render("- [x] done\n- [ ] todo")
    assert html.count('type="checkbox"') == 2
    assert html.count('disabled="disabled"') == 2 and 'checked="checked"' in html


def test_single_newlines_become_line_breaks():
    assert "<br" in render("line one\nline two")


def test_empty_input():
    assert render("") == "" and render(None) == "" and render("  \n ") == ""


def test_links_open_safely_and_bare_urls_are_linked():
    html = render("[site](https://example.com) and https://example.org/x")
    assert 'href="https://example.com"' in html and 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert 'href="https://example.org/x"' in html
    # relative / non-http links are kept but not forced into a new tab
    assert "target" not in render("[local](#/issue/ENG-1)")


@pytest.mark.parametrize(
    "source",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        "<iframe src='https://evil.example'></iframe>",
        '<a href="javascript:alert(1)">x</a>',
        "<b onmouseover=alert(1)>x</b>",
    ],
)
def test_raw_html_is_escaped(source):
    html = render(source)
    assert "<script" not in html and "<img" not in html and "<iframe" not in html
    # only harmless tags can appear (a linkified plain URL is fine); none may carry a script URL
    assert set(re.findall(r"<(\w+)", html)) <= {"p", "a", "br"}
    assert not re.search(r"<a [^>]*javascript:", html, re.I)
    assert "&lt;" in html  # the markup is shown as text instead of being interpreted


@pytest.mark.parametrize(
    "source",
    [
        "[x](javascript:alert(1))",
        "[x](JaVaScRiPt:alert(1))",
        "[x](vbscript:msgbox(1))",
        "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
        "![x](javascript:alert(1))",
    ],
)
def test_dangerous_urls_are_not_turned_into_links_or_images(source):
    html = render(source)
    assert "<a " not in html and "<img" not in html


def test_api_returns_rendered_html_for_issue_comment_project_document(client, team):
    issue = client.post("/api/issues", json={"team": "ENG", "title": "t", "description": "**hi**"}).json()
    assert issue["description"] == "**hi**"  # raw source is preserved for editing
    assert issue["description_html"] == "<p><strong>hi</strong></p>\n"

    comment = client.post("/api/issues/ENG-1/comments", json={"body": "- one\n- two"}).json()
    assert "<li>one</li>" in comment["body_html"]
    detail = client.get("/api/issues/ENG-1").json()
    assert "<li>two</li>" in detail["comments"][0]["body_html"]

    project = client.post("/api/projects", json={"team": "ENG", "name": "P", "description": "# Goals"}).json()
    assert project["description_html"] == "<h1>Goals</h1>\n"
    doc = client.post("/api/documents", json={"title": "D", "project_id": project["id"], "content": "`x`"}).json()
    assert doc["content_html"] == "<p><code>x</code></p>\n"
    assert client.get(f"/api/projects/{project['id']}").json()["documents"][0]["content_html"] == doc["content_html"]

    empty = client.post("/api/issues", json={"team": "ENG", "title": "no desc"}).json()
    assert empty["description_html"] == ""


def test_index_sends_a_content_security_policy(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_markdown_preview_endpoint(client):
    r = client.post("/api/markdown", json={"text": "# Hi <script>x</script>"})
    assert r.status_code == 200
    assert r.json()["html"].startswith("<h1>Hi") and "<script" not in r.json()["html"]
    assert client.post("/api/markdown", json={"text": "x" * 200_001}).status_code == 422
