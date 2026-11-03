"""
Help centre and legal pages (privacy, terms) from markdown files (SPEC §6).

Copied from kooistra-web 0.3.0 (`kooistra_web/content.py`, repo tag v0.14.0),
not imported (SPEC §2). Changes to the copy:
- the stylesheet lives in its own file, `docs.css`, next to this one;
- the menu at the top of each page starts with a link back to the shop;
- no `help_guard` (BikeShop's help pages are public).

How it works:
- Each markdown file is turned into a complete HTML page **once**, when the
  app starts. Edits to the markdown show after a restart.
- A route exists **only if its file does**: no `docs/legal/terms-of-service.md`,
  no `/legal/terms` (it answers 404).
- The pages load nothing from other sites and contain no inline styles or
  scripts: their only asset is one stylesheet from this server. So they work
  under a strict `Content-Security-Policy: default-src 'self'`.
- Links between the markdown files (`renting.md`, `privacy-policy.md`) are
  rewritten to the URLs they are served at (`/help/renting`, `/legal/privacy`).
"""
from __future__ import annotations

import html as _html
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

import markdown
from starlette.responses import HTMLResponse, Response

logger = logging.getLogger("bikeshop.content")

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_HREF = re.compile(r'href="([^"]+)"')
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)

# The stylesheet every page links to (served at `css_path`).
_CSS = (Path(__file__).parent / "docs.css").read_text(encoding="utf-8")

# The frame around every page: title, the stylesheet, the menu, the text.
_PAGE = (
    "<!DOCTYPE html>\n"
    '<html lang="en"><head>'
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>{title}</title>"
    '<link rel="stylesheet" href="{css_href}">'
    "</head><body>{nav}"
    '<main class="doc">{body}</main>'
    "</body></html>"
)


def _title_of(md_text: str, fallback: str) -> str:
    """The page title is the markdown's first "# Heading"."""
    m = _H1.search(md_text)
    return m.group(1).strip() if m else fallback


def _rewrite_links(html_body: str, link_map: dict) -> str:
    """Rewrite relative ``*.md`` links to their served URLs. External links untouched."""

    def repl(m: "re.Match") -> str:
        href = m.group(1)
        if _EXTERNAL.match(href):
            return m.group(0)
        path, sep, frag = href.partition("#")
        if not path.endswith(".md"):
            return m.group(0)
        stem = path.rsplit("/", 1)[-1][:-3]
        target = link_map.get(stem, stem)  # fallback: drop the .md (best effort)
        return f'href="{target}{sep}{frag}"'

    return _HREF.sub(repl, html_body)


def _render(md_text: str, link_map: dict) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])
    return _rewrite_links(md.convert(md_text), link_map)


def _nav(items: List[Tuple[str, str]]) -> str:
    if not items:
        return ""
    links = "".join(f'<a href="{_html.escape(url)}">{_html.escape(label)}</a>' for url, label in items)
    return f'<nav class="kw">{links}</nav>'


def _page(title: str, css_href: str, nav_html: str, body: str) -> str:
    return _PAGE.format(title=_html.escape(title), css_href=_html.escape(css_href), nav=nav_html, body=body)


def _add_html(app, path: str, html_str: str) -> None:
    async def route(_request) -> Response:
        return HTMLResponse(html_str)

    app.add_route(path, route, methods=["GET"], include_in_schema=False)


def add_content_pages(
    app,
    *,
    help_dir: Optional[Path] = None,
    privacy_file: Optional[Path] = None,
    terms_file: Optional[Path] = None,
    help_path: str = "/help",
    privacy_path: str = "/legal/privacy",
    terms_path: str = "/legal/terms",
    css_path: str = "/_docs.css",
    brand: Optional[str] = None,
    home: Optional[Tuple[str, str]] = None,
) -> None:
    """Mount a help centre and/or legal pages from the markdown the app ships.

    Each route is added **only if its source exists**. `help_dir` is a flat
    folder of `.md` articles (`index.md` becomes the `/help` landing page, else
    one is generated). `privacy_file` / `terms_file` are single markdown files.
    `home` is an optional first menu link, e.g. ("/", "BikeShop").
    """
    help_p = Path(help_dir) if help_dir else None
    privacy_p = Path(privacy_file) if privacy_file else None
    terms_p = Path(terms_file) if terms_file else None

    index_p: Optional[Path] = None
    articles: List[Tuple[str, Path]] = []
    if help_p and help_p.is_dir():
        for p in sorted(help_p.glob("*.md")):
            if p.stem == "index":
                index_p = p
            else:
                articles.append((p.stem, p))

    have_help = bool(index_p or articles)
    have_privacy = bool(privacy_p and privacy_p.is_file())
    have_terms = bool(terms_p and terms_p.is_file())

    if not (have_help or have_privacy or have_terms):
        logger.debug("add_content_pages: no docs found; nothing mounted")
        return

    # Link map (filename stem -> served URL), so shipped cross-links resolve.
    link_map: dict = {}
    if have_help:
        link_map["index"] = help_path
        link_map.update({slug: f"{help_path}/{slug}" for slug, _ in articles})
    if have_privacy:
        link_map[privacy_p.stem] = privacy_path
    if have_terms:
        link_map[terms_p.stem] = terms_path

    # The menu at the top of every page.
    nav_items: List[Tuple[str, str]] = [home] if home else []
    if have_help:
        nav_items.append((help_path, "Help"))
    if have_privacy:
        nav_items.append((privacy_path, "Privacy"))
    if have_terms:
        nav_items.append((terms_path, "Terms"))
    nav_html = _nav(nav_items)

    def render(text: str, fallback_title: str) -> str:
        return _page(_title_of(text, fallback_title), css_path, nav_html, _render(text, link_map))

    if have_help:
        if index_p:
            index_html = render(index_p.read_text(encoding="utf-8"), brand or "Help")
        else:
            items = "".join(
                f'<li><a href="{help_path}/{slug}">'
                f"{_html.escape(_title_of(p.read_text(encoding='utf-8'), slug))}</a></li>"
                for slug, p in articles
            )
            body = f"<h1>{_html.escape(brand or 'Help')}</h1><ul>{items}</ul>"
            index_html = _page(brand or "Help", css_path, nav_html, body)
        _add_html(app, help_path, index_html)
        for slug, p in articles:
            _add_html(app, f"{help_path}/{slug}", render(p.read_text(encoding="utf-8"), slug))

    if have_privacy:
        _add_html(app, privacy_path, render(privacy_p.read_text(encoding="utf-8"), "Privacy Policy"))
    if have_terms:
        _add_html(app, terms_path, render(terms_p.read_text(encoding="utf-8"), "Terms of Service"))

    async def css(_request) -> Response:
        return Response(_CSS, media_type="text/css")

    app.add_route(css_path, css, methods=["GET"], include_in_schema=False)

    mounted = [p for p, on in ((help_path, have_help), (privacy_path, have_privacy), (terms_path, have_terms)) if on]
    logger.info("content pages mounted: %s", ", ".join(mounted))
