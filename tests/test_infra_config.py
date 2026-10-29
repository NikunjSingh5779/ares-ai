"""Infrastructure configuration tests.

Verifies build-time config files stay correct across edits.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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


def test_fullstack_backend_forces_container_service_hosts() -> None:
    """The backend must not inherit the host-oriented .env database hosts."""
    path = PROJECT_ROOT / "docker" / "docker-compose.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    environment = data["services"]["backend"]["environment"]

    assert "@postgres:5432/" in environment["DATABASE_URL"]
    assert environment["REDIS_HOST"] == "redis"
    assert environment["CHROMA_HOST"] == "chromadb"


def test_dev_compose_local_llm_port_does_not_collide_with_backend() -> None:
    """The dev Compose backend already owns host 8080; Strata must use another port.

    A container request to ``host.docker.internal:8080`` would otherwise reach the
    backend's own published port instead of the local model.
    """
    compose = yaml.safe_load((PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    host_port = compose["services"]["backend"]["ports"][0].split(":", 1)[0]
    env_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    match = re.search(r"^LOCAL_LLM_BASE_URL=http://host\.docker\.internal:(\d+)/v1$", env_text, re.MULTILINE)

    assert match is not None, ".env.example must document the Compose local-model URL"
    assert match.group(1) != host_port, (
        f".env.example points the local model at host port {host_port}, which Compose already publishes for the backend"
    )


def test_chroma_is_pinned_to_client_version_and_data_path() -> None:
    """Pin both compose files to Chroma 1.5.9 and its /data persistence path."""
    fullstack = yaml.safe_load((PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    chroma = fullstack["services"]["chromadb"]
    assert chroma["image"] == "chromadb/chroma:1.5.9"
    assert chroma["healthcheck"]["disable"] is True
    # Chroma 1.x persists at /data; the legacy 0.5.0 path would lose all memory.
    assert chroma["volumes"] == ["chromadb-data:/data"]

    dev = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    dev_chroma = dev["services"]["chromadb"]
    assert dev_chroma["image"] == "chromadb/chroma:1.5.9"
    assert dev_chroma["volumes"] == ["chromadb_data:/data"]


def test_shell_scripts_are_forced_to_lf() -> None:
    """A CRLF entrypoint makes Docker fail before the container starts."""
    path = PROJECT_ROOT / ".gitattributes"
    text = path.read_text(encoding="utf-8")

    assert "*.sh text eol=lf" in text


def test_entrypoint_stamps_init_sql_bootstrap() -> None:
    """init.sql creates the schema, so Alembic must be stamped before upgrading."""
    path = PROJECT_ROOT / "docker" / "backend-entrypoint.sh"
    text = path.read_text(encoding="utf-8")

    assert "alembic stamp 0001" in text
    assert "alembic upgrade head" in text


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


# ── Prometheus alerting ─────────────────────────────────────────────────


MONITORING_DIR = PROJECT_ROOT / "docker" / "monitoring"
ALERT_RULES = MONITORING_DIR / "alert-rules.yml"


def _alert_rules() -> list[dict[str, Any]]:
    """Load and return every rule in the tracked alert-rules file."""
    data = yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8"))
    return [rule for group in data["groups"] for rule in group["rules"]]


def test_alert_rules_have_required_fields() -> None:
    """Every rule needs an expression, a severity, and a human summary."""
    rules = _alert_rules()

    assert rules, "alert-rules.yml must define at least one rule"
    for rule in rules:
        assert rule.get("alert"), f"rule without alert name: {rule}"
        assert rule.get("expr"), f"{rule['alert']} has no expression"
        assert rule["labels"]["severity"] in {"warning", "critical"}, (
            f"{rule['alert']} must set labels.severity to warning or critical"
        )
        assert rule["annotations"]["summary"], f"{rule['alert']} has no summary"


def test_alert_rules_cover_availability_agents_and_live_trading() -> None:
    """The rules must keep the core failure modes covered."""
    names = {rule["alert"] for rule in _alert_rules()}

    assert {
        "AresBackendDown",
        "AresBackendHighErrorRate",
        "AresBackendSlowRequests",
        "AresAgentErrorRateHigh",
        "AresModelFallbackSpike",
        "AresLiveOrderFailures",
        "AresKillSwitchActive",
    } <= names


def test_alert_rules_reference_emitted_metrics() -> None:
    """A rule that names a metric the backend never emits can never fire."""
    metrics_source = (PROJECT_ROOT / "backend" / "core" / "metrics.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'"(ares_[a-z0-9_]+)"', metrics_source))
    referenced = {metric for rule in _alert_rules() for metric in re.findall(r"\b(ares_[a-z0-9_]+)", rule["expr"])}

    def base_metric(name: str) -> str:
        """Histograms expose _bucket/_sum/_count series from one registration."""
        for suffix in ("_bucket", "_sum", "_count"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    unknown = {name for name in referenced if name not in emitted and base_metric(name) not in emitted}

    assert referenced, "alert rules must reference at least one ARES metric"
    assert not unknown, f"rules reference metrics the backend does not emit: {unknown}"


def test_prometheus_loads_the_tracked_alert_rules() -> None:
    """Prometheus only evaluates a rule file that is listed and mounted."""
    config = yaml.safe_load((MONITORING_DIR / "prometheus.yml").read_text(encoding="utf-8"))

    assert "/etc/prometheus/alert-rules.yml" in config["rule_files"]

    root_compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    full_compose = (PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "docker/monitoring/alert-rules.yml:/etc/prometheus/alert-rules.yml:ro" in root_compose
    assert "./monitoring/alert-rules.yml:/etc/prometheus/alert-rules.yml:ro" in full_compose


def test_compose_uses_one_tracked_monitoring_set() -> None:
    """Both compose files must use docker/monitoring, not the gitignored copies."""
    root_compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    full_compose = (PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "docker/prometheus/" not in root_compose
    assert "docker/grafana/" not in root_compose
    assert "docker/monitoring/prometheus.yml" in root_compose
    assert "docker/monitoring/grafana-datasources.yml" in root_compose
    assert "docker/monitoring/grafana-dashboards.yml" in root_compose

    assert "./monitoring/prometheus.yml" in full_compose
    assert "./monitoring/grafana-datasources.yml" in full_compose


def test_grafana_dashboards_are_valid_and_mounted() -> None:
    """Both tracked dashboards must parse and be mounted by both compose files."""
    root_compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    full_compose = (PROJECT_ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    for name in ("grafana-dashboard.json", "grafana-overview.json"):
        data = json.loads((MONITORING_DIR / name).read_text(encoding="utf-8"))
        assert data["panels"], f"{name} must define at least one panel"
        assert f"monitoring/{name}:/var/lib/grafana/dashboards/" in root_compose
        assert f"./monitoring/{name}:/var/lib/grafana/dashboards/" in full_compose


# ── Docker-internal service addresses ────────────────────────────────────


def test_fullstack_compose_uses_internal_service_hostnames() -> None:
    """Host-facing .env defaults must not break service-to-service traffic.

    The full-stack Compose project reads the root .env file, whose host-run
    defaults use localhost and a published ChromaDB port. Containers must use
    Compose DNS names and container ports instead.
    """
    path = PROJECT_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    backend_env = compose["services"]["backend"]["environment"]

    assert backend_env["DATABASE_URL"] == (
        "postgresql+asyncpg://${POSTGRES_USER:-ares}:${POSTGRES_PASSWORD:-changeme_in_production}"
        "@postgres:5432/${POSTGRES_DB:-ares_ai}"
    )
    assert backend_env["REDIS_HOST"] == "redis"
    assert backend_env["CHROMA_HOST"] == "chromadb"
    assert backend_env["CHROMA_PORT"] == 8000


# ── Scheduled model-catalog workflow ────────────────────────────────────

MODEL_CATALOG_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "model-catalog.yml"


def _workflow(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} must be a YAML mapping"
    return data


def _workflow_triggers(workflow: dict[Any, Any]) -> dict[Any, Any]:
    # PyYAML resolves the YAML 1.1 key ``on`` to the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "the workflow must declare triggers"
    return triggers


def _workflow_steps(workflow: dict[Any, Any]) -> list[dict[Any, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _probe_steps(workflow: dict[Any, Any]) -> list[dict[Any, Any]]:
    return [step for step in _workflow_steps(workflow) if "scripts/test_free_models.py" in str(step.get("run", ""))]


def _job_for_step(workflow: dict[Any, Any], step: dict[Any, Any]) -> dict[Any, Any]:
    return next(
        job for job in workflow["jobs"].values() if any(candidate is step for candidate in job.get("steps", []))
    )


def test_model_catalog_workflow_is_scheduled_and_manual() -> None:
    triggers = _workflow_triggers(_workflow(MODEL_CATALOG_WORKFLOW))

    assert triggers.get("schedule") == [{"cron": "17 6 * * 1"}], "the weekly check must stay on Monday 06:17 UTC"
    assert "workflow_dispatch" in triggers
    # The job reads a repository secret; it must not run for PRs or every push.
    assert "push" not in triggers
    assert "pull_request" not in triggers


def test_model_catalog_workflow_runs_the_probe_once() -> None:
    workflow = _workflow(MODEL_CATALOG_WORKFLOW)
    probes = _probe_steps(workflow)

    assert len(probes) == 1, "the workflow must run the roster probe exactly once"
    probe = probes[0]
    assert probe["run"].strip() == "uv run python scripts/test_free_models.py"
    assert not probe.get("continue-on-error"), "a failing probe must fail the job"
    assert "if" not in probe, "the probe must not be conditional"
    assert not _job_for_step(workflow, probe).get("continue-on-error"), "a failing probe must fail the job"


def test_model_catalog_workflow_uses_the_repository_secret() -> None:
    workflow = _workflow(MODEL_CATALOG_WORKFLOW)
    probes = _probe_steps(workflow)

    assert len(probes) == 1
    job = _job_for_step(workflow, probes[0])
    # The secret may be set at job or step level; both are valid.
    env = {**job.get("env", {}), **probes[0].get("env", {})}
    assert "secrets.OPENROUTER_API_KEY" in str(env.get("OPENROUTER_API_KEY", ""))
    assert workflow.get("permissions") == {"contents": "read"}


def test_model_catalog_workflow_fails_clearly_without_the_secret() -> None:
    workflow = _workflow(MODEL_CATALOG_WORKFLOW)
    steps = _workflow_steps(workflow)
    guards = [step for step in steps if "OPENROUTER_API_KEY is not set" in str(step.get("run", ""))]

    assert guards, "a missing secret must fail with an explicit error"
    assert "::error::" in guards[0]["run"]
    assert "exit 1" in guards[0]["run"]
    assert steps.index(guards[0]) < steps.index(_probe_steps(workflow)[0]), "fail before the probe starts"


def test_model_catalog_workflow_allows_the_full_probe_to_finish() -> None:
    workflow = _workflow(MODEL_CATALOG_WORKFLOW)

    for job in workflow["jobs"].values():
        assert job.get("timeout-minutes", 0) >= 45, "the full probe plus install can exceed 30 minutes"
