"""Guards for app.js that no API test can give: every delete asks first, and nothing uses native dialogs."""

import re
from pathlib import Path

APP_JS = (Path(__file__).parent.parent / "src" / "local_linear" / "static" / "app.js").read_text(encoding="utf-8")


def test_every_delete_asks_for_confirmation_first():
    lines = APP_JS.splitlines()
    sites = [i for i, line in enumerate(lines) if 'method: "DELETE"' in line]
    assert len(sites) >= 5  # issue, comment, project, milestone, document: fails if the search stops matching
    for i in sites:
        # the confirmation is on the same line or in the few lines of the handler above it
        assert any("confirmDialog(" in line for line in lines[max(0, i - 3): i + 1]), f"app.js:{i + 1} deletes without asking"


def test_native_confirm_is_not_used():
    # window.confirm() can be suppressed by browsers and webviews, which made Delete look broken
    code = "\n".join(line for line in APP_JS.splitlines() if not line.lstrip().startswith("//"))  # comments may mention it
    assert not re.search(r"(?<![\w.])(?:window\.)?confirm\(", code)
