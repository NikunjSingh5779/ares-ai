"""Infrastructure configuration tests.

Verifies build-time config files stay correct across edits.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── .agents/skills.json ──────────────────────────────────────────────────

SKILLS_JSON = PROJECT_ROOT / ".agents" / "skills.json"


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


# ── .github/dependabot.yml ──────────────────────────────────────────────

DEPENDABOT_YML = PROJECT_ROOT / ".github" / "dependabot.yml"


def test_dependabot_ignores_typescript_major() -> None:
    """dependabot must ignore major version bumps for typescript.

    TypeScript 7.0 does not provide the compiler API that Next.js 16.x
    requires.  Without this ignore rule, dependabot will repeatedly open
    an unmergeable PR on every new TS 7.x release.
    """
    data = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))

    npm_updates = [u for u in data.get("updates", []) if u.get("package-ecosystem") == "npm"]
    assert npm_updates, "No npm update config found in dependabot.yml"

    for entry in npm_updates:
        ignores = entry.get("ignore", [])
        for rule in ignores:
            name = rule.get("dependency-name", "")
            update_types = rule.get("update-types", [])
            if name == "typescript" and "version-update:semver-major" in update_types:
                return  # found it

    assert False, (
        "dependabot.yml has no ignore rule for typescript major version bumps. "
        "Add:\n"
        "  ignore:\n"
        '    - dependency-name: "typescript"\n'
        '      update-types: ["version-update:semver-major"]'
    )
