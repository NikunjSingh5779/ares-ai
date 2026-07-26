"""Infrastructure configuration tests.

Verifies build-time config files stay correct across edits.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── frontend/Dockerfile ──────────────────────────────────────────────────


def test_frontend_dockerfile_declares_api_url_arg() -> None:
    """frontend/Dockerfile must declare ARG NEXT_PUBLIC_API_URL before build."""
    path = PROJECT_ROOT / "frontend" / "Dockerfile"
    text = path.read_text(encoding="utf-8")

    assert "ARG NEXT_PUBLIC_API_URL" in text, (
        f"{path} is missing 'ARG NEXT_PUBLIC_API_URL' — "
        "NEXT_PUBLIC_* vars are inlined at build time and won't work from "
        "runtime environment."
    )


def test_frontend_dockerfile_has_api_url_env() -> None:
    """frontend/Dockerfile must set ENV from the ARG so pnpm build sees it.

    Without ``ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL`` the ARG is
    declared but never forwarded to the build process.
    """
    path = PROJECT_ROOT / "frontend" / "Dockerfile"
    text = path.read_text(encoding="utf-8")

    assert "ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL" in text, (
        f"{path} needs 'ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL' after the ARG declaration."
    )


# ── Root docker-compose.yml (11-service full stack) ────────────────────


def test_root_compose_has_api_url_build_arg() -> None:
    """Root docker-compose.yml must pass NEXT_PUBLIC_API_URL as a build arg."""
    path = PROJECT_ROOT / "docker-compose.yml"
    text = path.read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_API_URL:" in text, (
        f"{path} is missing NEXT_PUBLIC_API_URL build arg — the frontend "
        "service will inherit whatever was baked into the image."
    )
    assert "build:" in text and "args:" in text, f"{path} must have a 'build.args' section for the frontend service."


# ── docker/docker-compose.yml (7-service core stack) ───────────────────


def test_fullstack_compose_has_api_url_build_arg() -> None:
    """Full-stack docker-compose must pass NEXT_PUBLIC_API_URL as a build arg."""
    path = PROJECT_ROOT / "docker" / "docker-compose.yml"
    text = path.read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_API_URL:" in text, (
        f"{path} is missing NEXT_PUBLIC_API_URL build arg — runtime "
        "environment alone has no effect on NEXT_PUBLIC_* vars."
    )


# ── Default fallback consistency ────────────────────────────────────────


def test_api_ts_fallback_matches_dev_stack() -> None:
    """The api.ts fallback URL should match the root docker-compose stack's default.

    The root ``docker-compose.yml`` (11-service full stack) maps the backend
    to host port 8000 — the fallback must match so the dashboard works out
    of the box without a .env file.
    """
    path = PROJECT_ROOT / "frontend" / "src" / "lib" / "api.ts"
    text = path.read_text(encoding="utf-8")

    assert "localhost:8000" in text, (
        f"{path} fallback URL doesn't resolve to the root docker-compose stack's default backend port (8000)."
    )


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
