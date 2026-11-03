"""
Help centre and legal pages, rendered from the markdown in docs/ (SPEC §6).

`mount_content_pages(app)` is what main.py calls: it points the copied
renderer (content.py) at BikeShop's files. A page whose file is missing
simply doesn't exist (404).
"""
from pathlib import Path

from ..config import DOCS_DIR
from .content import add_content_pages


def mount_content_pages(app, docs_dir: Path = DOCS_DIR) -> None:
    """/help and /help/<article> from docs/help/, /legal/privacy and /legal/terms from docs/legal/."""
    add_content_pages(
        app,
        help_dir=docs_dir / "help",
        privacy_file=docs_dir / "legal" / "privacy-policy.md",
        terms_file=docs_dir / "legal" / "terms-of-service.md",
        brand="BikeShop help",
        home=("/", "BikeShop"),   # back to the shop from every page
    )
