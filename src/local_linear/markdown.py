"""Markdown to HTML for descriptions, comments and documents.

Safety comes from the parser configuration, not from after-the-fact sanitising: raw HTML in the
source is escaped (``html=False``) and markdown-it rejects unsafe link targets such as
``javascript:``, so the HTML returned here can be assigned to ``innerHTML`` by the UI.
"""

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
    .enable(["table", "strikethrough", "linkify"])
    .use(tasklists_plugin)  # "- [ ] item" renders as a (read-only) checkbox
)


def _link_open(self, tokens, idx, options, env):
    token = tokens[idx]
    if (token.attrGet("href") or "").lower().startswith(("http://", "https://")):
        token.attrSet("target", "_blank")
        token.attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _link_open)


def render(text: str | None) -> str:
    """Render Markdown source to an HTML fragment ('' for empty input)."""
    return _md.render(text) if text and text.strip() else ""
