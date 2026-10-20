"""Structure tests for the ICM layer.

Enforces ADR-008: every working folder states its contract, the root entry file stays a
catalog, and relative links in the entry documents resolve. These tests are cheap and
catch structural rot that ordinary unit tests do not see.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

WORKING_FOLDERS = (
    "agents",
    "backend",
    "backtesting",
    "configs",
    "database",
    "docker",
    "docs",
    "frontend",
    "landing",
    "live_trading",
    "migrations",
    "paper_trading",
    "scripts",
    "tests",
)

ENTRY_DOCS = (
    ROOT / "AGENTS.md",
    ROOT / "docs" / "00-INDEX.md",
    ROOT / "docs" / "map" / "AGENTS.md",
)

# Markdown inline links: [label](target)
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _relative_links(doc: Path) -> Iterator[str]:
    """Yield local link targets (fragments and external URLs removed)."""
    text = doc.read_text(encoding="utf-8")
    for target in _LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        local = target.split("#", maxsplit=1)[0]
        if local:
            yield local


@pytest.mark.parametrize("folder", WORKING_FOLDERS)
def test_every_working_folder_has_a_contract(folder: str) -> None:
    """Each folder states what it reads, does, writes, and what a human checks."""
    assert (ROOT / folder / "CONTEXT.md").is_file(), f"{folder}/CONTEXT.md is missing"


def test_entry_file_stays_a_catalog() -> None:
    """The root entry file routes; it must not grow back into the full spec."""
    lines = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 110, f"AGENTS.md is {len(lines)} lines; move payload to docs/"


@pytest.mark.parametrize("doc", ENTRY_DOCS, ids=lambda path: str(path.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    """Every local link in an entry document points at a real file."""
    missing = [target for target in _relative_links(doc) if not (doc.parent / target).exists()]
    assert missing == [], f"{doc.relative_to(ROOT)} has broken links: {missing}"


def test_status_has_a_verified_date() -> None:
    """Status is a measured snapshot, not a label."""
    text = (ROOT / "docs" / "02-STATUS.md").read_text(encoding="utf-8")
    assert re.search(r"\*\*Last verified:\*\* \d{4}-\d{2}-\d{2}", text)


def test_every_map_card_is_indexed() -> None:
    """A card that the map does not point at is invisible to a cold reader."""
    index = (ROOT / "docs" / "map" / "AGENTS.md").read_text(encoding="utf-8")
    cards = sorted((ROOT / "docs" / "map" / "objects").glob("*.md"))
    cards += sorted((ROOT / "docs" / "map" / "processes").glob("*.md"))
    assert cards, "no map cards found"
    for card in cards:
        assert card.name in index, f"{card.name} is not linked from docs/map/AGENTS.md"
