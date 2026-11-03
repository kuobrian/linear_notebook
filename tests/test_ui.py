"""Browser tests for static/app.js: a real server in a subprocess, driven by Chrome or Edge.

No browser download is needed, Playwright uses the one installed on the machine. When neither can be
started the tests are skipped.
"""

import itertools
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

SERVER = "from local_linear.main import main; main()"
keys = itertools.count(1)


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    db = tmp_path_factory.mktemp("ui") / "ui.db"
    env = {**os.environ, "LOCAL_LINEAR_DB": f"sqlite:///{db.as_posix()}", "LOCAL_LINEAR_SEED": "0"}
    env.pop("LOCAL_LINEAR_TEST_DB", None)
    proc = subprocess.Popen([sys.executable, "-c", SERVER, "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/api/meta").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("the server did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        for channel in ("chrome", "msedge"):
            try:
                b = p.chromium.launch(channel=channel)
                break
            except playwright_api.Error:
                continue
        else:
            pytest.skip("neither Chrome nor Edge could be started")
        yield b
        b.close()


@pytest.fixture()
def page(browser, base_url):
    # fresh localStorage for every test. The app's CSP forbids eval, which Playwright's wait_for_function
    # needs; bypassing it also makes the XSS test stricter, the page itself must not run injected HTML.
    context = browser.new_context(bypass_csp=True)
    page = context.new_page()
    page.set_default_timeout(5000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield page
    context.close()
    assert not errors, f"uncaught JavaScript errors: {errors}"


@pytest.fixture()
def team(base_url):
    """A team of its own, so tests do not see each other's issues."""
    key = f"T{next(keys)}"
    r = httpx.post(base_url + "/api/teams", json={"key": key, "name": f"Team {key}"})
    assert r.status_code == 201, r.text
    return r.json()


def add_issue(base_url, team, title, status="backlog", **extra):
    status_id = next(s["id"] for s in team["statuses"] if s["type"] == status)
    r = httpx.post(base_url + "/api/issues", json={"team": team["key"], "title": title, "status_id": status_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def open_team(page, base_url, team):
    page.goto(f"{base_url}/#/issues?team={team['key']}")
    page.wait_for_selector("h1")


def test_list_groups_issues_by_status(page, base_url, team):
    add_issue(base_url, team, "First")
    add_issue(base_url, team, "Second")
    add_issue(base_url, team, "Working", status="started")
    open_team(page, base_url, team)

    heads = page.locator(".group-head.collapsible")
    assert heads.count() == 2
    assert page.locator(".row").count() == 3
    assert "2" in heads.filter(has_text="Backlog").inner_text()


def test_groups_collapse_with_mouse_and_keyboard_and_stay_collapsed_after_reload(page, base_url, team):
    add_issue(base_url, team, "Hide me")
    open_team(page, base_url, team)
    head = page.locator(".group-head.collapsible", has_text="Backlog")
    row = page.locator(".row", has_text="Hide me")

    head.click()
    assert not row.is_visible() and head.get_attribute("aria-expanded") == "false"
    page.reload()
    page.wait_for_selector(".group-head")
    assert not page.locator(".row", has_text="Hide me").is_visible()  # remembered

    head.focus()
    page.keyboard.press("Enter")
    assert page.locator(".row", has_text="Hide me").is_visible()


def test_the_plus_button_in_a_group_does_not_collapse_it(page, base_url, team):
    add_issue(base_url, team, "Stay")
    open_team(page, base_url, team)
    page.locator(".group-head .add").click()
    assert page.locator("[role=dialog]").is_visible()
    assert page.locator(".row", has_text="Stay").is_visible()


def test_new_issue_modal_creates_an_issue_with_the_keyboard(page, base_url, team):
    open_team(page, base_url, team)
    page.keyboard.press("c")
    page.locator("[role=dialog] input").first.fill("Made in the browser")
    page.keyboard.press("Control+Enter")

    page.wait_for_selector(".row")
    assert f"Created {team['key']}-1" in page.locator("#toast").inner_text()
    assert page.locator(".row .title").inner_text() == "Made in the browser"


def test_search_filters_and_treats_percent_literally(page, base_url, team):
    add_issue(base_url, team, "100% sure")
    add_issue(base_url, team, "Plain one")
    open_team(page, base_url, team)

    page.fill("#search", "%")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.row').length === 1")
    assert page.locator(".row .title").inner_text() == "100% sure"

    page.fill("#search", "")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelectorAll('.row').length === 2")


def test_board_drag_changes_the_status(page, base_url, team):
    issue = add_issue(base_url, team, "Drag me")
    open_team(page, base_url, team)
    page.get_by_role("button", name="Board").click()

    page.locator(".card", has_text="Drag me").drag_to(page.locator(".column", has_text="In Progress"))

    page.wait_for_function("document.querySelector('.column:nth-child(3) .card')")
    assert httpx.get(f"{base_url}/api/issues/{issue['id']}").json()["status"]["name"] == "In Progress"


def test_issue_page_changes_status_and_posts_a_comment(page, base_url, team):
    issue = add_issue(base_url, team, "Detail")
    page.goto(f"{base_url}/#/issue/{issue['identifier']}")
    page.wait_for_selector(".title-input")

    page.locator("textarea.field").fill("**bold** note")
    page.get_by_role("button", name="Comment", exact=True).click()
    page.wait_for_selector(".comment .body strong")  # the page re-rendered, so it is stable now

    page.locator(".prop", has_text="Status").locator("select").select_option(label="Done")
    for _ in range(50):  # the change is saved by a request the page makes after the click
        data = httpx.get(f"{base_url}/api/issues/{issue['id']}").json()
        if data["status"]["type"] == "completed":
            break
        time.sleep(0.1)
    assert data["status"]["type"] == "completed" and data["completed_at"]
    assert data["comments"][0]["body"] == "**bold** note"


def test_deleting_an_issue_asks_first_and_cancel_keeps_it(page, base_url, team):
    issue = add_issue(base_url, team, "Keep or lose")
    page.goto(f"{base_url}/#/issue/{issue['identifier']}")
    page.get_by_role("button", name="Delete", exact=True).click()
    dialog = page.locator("[role=dialog]")
    dialog.get_by_role("button", name="Cancel").click()
    assert httpx.get(f"{base_url}/api/issues/{issue['id']}").status_code == 200

    page.get_by_role("button", name="Delete", exact=True).click()
    dialog.get_by_role("button", name="Delete").click()
    page.wait_for_function("location.hash.startsWith('#/issues')")
    assert httpx.get(f"{base_url}/api/issues/{issue['id']}").status_code == 404


def test_escape_closes_the_confirmation_and_deletes_nothing(page, base_url, team):
    issue = add_issue(base_url, team, "Still here")
    page.goto(f"{base_url}/#/issue/{issue['identifier']}")
    page.get_by_role("button", name="Delete", exact=True).click()
    page.wait_for_selector("[role=dialog]")
    page.keyboard.press("Escape")
    assert not page.locator("[role=dialog]").is_visible()
    assert httpx.get(f"{base_url}/api/issues/{issue['id']}").status_code == 200


def test_html_in_titles_and_descriptions_is_shown_as_text_not_run(page, base_url, team):
    evil = '<img src=x onerror="window.pwned=1">'
    issue = add_issue(base_url, team, evil, description=f"{evil}\n\n[x](javascript:window.pwned=2)")
    open_team(page, base_url, team)
    assert page.locator(".row .title").inner_text() == evil
    page.goto(f"{base_url}/#/issue/{issue['identifier']}")
    page.wait_for_selector(".md-view")
    page.wait_for_timeout(300)  # an onerror handler would have fired by now
    assert page.evaluate("window.pwned") is None
    assert page.locator(".md-view a[href^='javascript']").count() == 0


def test_project_page_adds_and_removes_a_milestone(page, base_url, team):
    project = httpx.post(base_url + "/api/projects", json={"team": team["key"], "name": "Proj"}).json()
    page.goto(f"{base_url}/#/project/{project['id']}")
    page.wait_for_selector(".project-page")

    page.get_by_placeholder("New milestone name").fill("Beta")
    page.locator(".ms-row", has=page.get_by_placeholder("New milestone name")).get_by_role("button", name="Add").click()
    page.wait_for_selector(".ms-row strong:text('Beta')")

    page.locator(".ms-row", has_text="Beta").get_by_role("button", name="✕").click()
    page.locator("[role=dialog]").get_by_role("button", name="Delete").click()
    page.wait_for_function("!document.body.innerText.includes('Beta')")
    assert httpx.get(f"{base_url}/api/projects/{project['id']}").json()["milestones"] == []


def test_database_page_copies_data_and_refuses_a_second_copy(page, base_url, team, tmp_path):
    add_issue(base_url, team, "Copy me")
    target = tmp_path / "copy.db"
    page.goto(f"{base_url}/#/database")
    page.wait_for_selector(".db-page")
    assert "SQLite" in page.locator(".db-page .chip").first.inner_text()

    page.get_by_placeholder("postgresql://").fill(f"sqlite:///{target.as_posix()}")
    page.get_by_role("button", name="Copy data").click()
    page.wait_for_selector(".db-result strong")
    assert page.locator(".db-result strong").inner_text().startswith("Copied ")
    assert target.exists()

    page.get_by_role("button", name="Copy data").click()  # the target now has data
    page.wait_for_function("document.querySelector('#toast').className.includes('error')")
    assert page.locator(".db-result strong").count() == 0


def test_routes_and_unknown_issue(page, base_url, team):
    page.goto(f"{base_url}/#/projects")
    page.wait_for_selector("h1:text('Projects')")
    page.goto(f"{base_url}/#/issue/NOPE-1")
    page.wait_for_function("document.querySelector('#toast').className.includes('error')")


def test_theme_choice_is_remembered(page, base_url, team):
    open_team(page, base_url, team)
    page.get_by_role("button", name="Toggle theme").click()
    chosen = page.evaluate("document.documentElement.dataset.theme")
    assert chosen in ("light", "dark")
    page.reload()
    page.wait_for_selector("h1")
    assert page.evaluate("document.documentElement.dataset.theme") == chosen
