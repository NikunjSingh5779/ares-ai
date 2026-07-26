"""Infrastructure configuration tests.

Verify that Dockerfiles and docker-compose files have correct build-arg
wiring for NEXT_PUBLIC_API_URL — a build-time ARG that Next.js inlines into
the compiled bundle (runtime env vars have no effect).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Dockerfile ──────────────────────────────────────────────────────────

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
        f"{path} needs 'ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL' "
        "after the ARG declaration."
    )


# ── Root docker-compose.yml (5-service dev) ─────────────────────────────

def test_root_compose_has_api_url_build_arg() -> None:
    """Root docker-compose.yml must pass NEXT_PUBLIC_API_URL as a build arg."""
    path = PROJECT_ROOT / "docker-compose.yml"
    text = path.read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_API_URL:" in text, (
        f"{path} is missing NEXT_PUBLIC_API_URL build arg — the frontend "
        "service will inherit whatever was baked into the image."
    )
    assert "build:" in text and "args:" in text, (
        f"{path} must have a 'build.args' section for the frontend service."
    )


# ── docker/docker-compose.yml (11-service full stack) ──────────────────

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
    """The api.ts fallback URL should match the 5-service dev stack's default.

    The 5-service stack (root docker-compose.yml) maps the backend to host
    port 8000 — the fallback must match so the dashboard works out of the
    box without a .env file.
    """
    path = PROJECT_ROOT / "frontend" / "src" / "lib" / "api.ts"
    text = path.read_text(encoding="utf-8")

    assert "localhost:8000" in text, (
        f"{path} fallback URL doesn't resolve to the 5-service dev stack's "
        "default backend port (8000)."
    )
