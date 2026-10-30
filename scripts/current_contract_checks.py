"""Static guards against reintroducing removed version adapters."""

from __future__ import annotations

from pathlib import Path
import re

from server.services.artifact_contract import validate_skill_artifact_contract_content


RETIRED_PRODUCTION_SYMBOLS = (
    "_canonicalize_node_artifacts",
    "normalize_persisted_figure_route",
    "canonicalize_method_contract",
    "migrate_retired_illustration_mode",
    "_migrate_legacy_simulation_package_before_revalidation",
    "_legacy_revision_lacked_authoring_tools",
    "_is_heavy_legacy_experiment_snapshot",
    "LEGACY_EXPERIMENT_SNAPSHOT_MIGRATION_BYTES",
    "simulation_result_analysis_v2",
    "mcp__codex__codex",
    "method contract must use schema=1",
    "if int(payload.get('schema') or 0) >= 2:",
    'root / str(blueprint.get("entrypoint")',
)


def retired_contract_references(root: Path, paths: list[Path]) -> list[tuple[str, int, str]]:
    """Return production references to deliberately removed adapters."""
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        if "tests" in path.parts or path.name in {
            "current_contract_checks.py", "check_code_standards.py",
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for symbol in RETIRED_PRODUCTION_SYMBOLS:
                if symbol in line:
                    findings.append((
                        path.relative_to(root).as_posix(), line_number,
                        f"retired contract adapter reintroduced: {symbol}",
                    ))
    return findings


def artifact_contract_aliases(root: Path) -> list[tuple[str, int, str]]:
    """Keep the workflow producer contract free of alternate output paths."""
    path = root / "server/services/project_scaffold.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = text.find("WORKFLOW_ARTIFACT_CONTRACT =")
    end = text.find("\ndef get_workflow_artifact_contract", marker)
    contract = text[marker:end] if marker >= 0 and end > marker else ""
    if '"aliases"' not in contract:
        return []
    line = text[: marker + contract.find('"aliases"')].count("\n") + 1
    return [(path.relative_to(root).as_posix(), line, "artifact aliases are prohibited")]


def method_contract_schema_downgrades(
    root: Path, paths: list[Path],
) -> list[tuple[str, int, str]]:
    """Reject method-contract writers that bypass the current version constant."""
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        if "tests" in path.parts or not path.name.startswith("method_contract"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        marker = 'payload["schema"] = 1'
        if marker not in text:
            continue
        line = text[: text.find(marker)].count("\n") + 1
        findings.append((
            path.relative_to(root).as_posix(),
            line,
            "method contract writer must use METHOD_CONTRACT_SCHEMA",
        ))
    return findings


def figure_backend_takeovers(root: Path) -> list[tuple[str, int, str]]:
    """The runtime validates rich-SVG output; it must never replace the artwork."""
    path = root / "server/services/figure_engine.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    markers = ("render_communication_svg", "communication_renderer")
    findings = []
    for marker in markers:
        if marker not in text:
            continue
        line = text[: text.find(marker)].count("\n") + 1
        findings.append((
            path.relative_to(root).as_posix(), line,
            "figure backend must validate, not replace, model-authored rich SVG",
        ))
    return findings


def current_contract_findings(
    root: Path, paths: list[Path],
) -> list[tuple[str, int, str]]:
    findings = [
        *retired_contract_references(root, paths),
        *artifact_contract_aliases(root),
        *method_contract_schema_downgrades(root, paths),
        *figure_backend_takeovers(root),
    ]
    skills_root = root / "merak-skills"
    if skills_root.is_dir():
        for skill_file in sorted(skills_root.glob("*/SKILL.md")):
            if skill_file.parent.name.startswith("skills-codex"):
                continue
            try:
                validate_skill_artifact_contract_content(
                    skill_file.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, ValueError) as error:
                findings.append((
                    skill_file.relative_to(root).as_posix(),
                    1,
                    f"skill artifact contract invalid: {error}",
                ))
            text = skill_file.read_text(encoding="utf-8-sig", errors="replace")
            if re.search(
                r"Write JSON with [`\"]schema:\s*1|"
                r"METHOD_CONTRACT(?:\.json)?[^\n]{0,120}schema\s*[:=]\s*1",
                text,
                re.IGNORECASE,
            ):
                findings.append((
                    skill_file.relative_to(root).as_posix(),
                    1,
                    "active skill contains a schema-1 instruction",
                ))
    return findings
