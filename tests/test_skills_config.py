"""Tests for .agents/skills.json configuration.

Verifies no hardcoded absolute paths that would break on other machines.
"""

from __future__ import annotations

import json
from pathlib import Path

SKILLS_JSON = Path(__file__).resolve().parent.parent / ".agents" / "skills.json"


def test_skills_json_no_absolute_paths() -> None:
    """Every path in skills.json should be repo-relative, not absolute."""
    if not SKILLS_JSON.exists():
        return  # file removed; nothing to validate

    data = json.loads(SKILLS_JSON.read_text(encoding="utf-8"))

    for entry in data.get("entries", []):
        path = entry.get("path", "")
        # Reject drive-letter roots (Windows) and leading slashes (Unix)
        assert not path.startswith(("/", "\\", "C:", "D:")), (
            f"A machine-specific absolute path was found in {SKILLS_JSON}: {path!r}. Use a repo-relative path instead."
        )
