from pathlib import Path
import re
import pytest

from server.services.paper_drafting import (
    VENUE_TEMPLATE_BUNDLES,
    PaperDraftingService,
)
from server.services.skill_registry import (
    SkillRegistry,
    normalize_skill_runtime_contract,
)


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n\n# {name}\n\nActive skill.\n",
        encoding="utf-8",
    )


def test_registry_loads_only_direct_skill_packages(tmp_path: Path) -> None:
    _write_skill(tmp_path, "paper-write")
    (tmp_path / "shared-references").mkdir()

    registry = SkillRegistry()

    assert registry.scan_directory(tmp_path) == 1
    assert [skill.id for skill in registry.list_all()] == ["paper-write"]


def test_runtime_skill_contract_allows_same_model_in_fresh_review_session() -> None:
    source = (
        "---\nname: review-skill\n---\n\n"
        "Require a different model family from the executor.\n"
    )

    normalized = normalize_skill_runtime_contract(source)

    assert normalized.startswith("---\nname: review-skill\n---\n")
    assert "Reviewer and Executor MAY use the same provider" in normalized
    assert "context-isolated" in normalized
    assert "read-only" in normalized
    assert "reject, skip, downgrade" in normalized


def test_registry_rejects_retired_tool_names_instead_of_translating() -> None:
    with pytest.raises(ValueError, match="Unsupported reviewer transport"):
        normalize_skill_runtime_contract("Invoke mcp__codex__codex for review.")


def test_registry_rejects_versioned_skill_without_current_contract(tmp_path: Path) -> None:
    source = tmp_path / "bad-contract" / "SKILL.md"
    source.parent.mkdir()
    source.write_text(
        '---\nname: bad-contract\n'
        'artifact-outputs: ["ideas/SELECTED_IDEA.json"]\n'
        'artifact-contracts: {"ideas/SELECTED_IDEA.json": 1}\n---\n',
        encoding="utf-8",
    )
    from server.services.skill_registry import parse_skill_md

    assert parse_skill_md(source) is None


def test_legacy_platform_mirrors_are_excluded_from_docker_context() -> None:
    repository = Path(__file__).resolve().parents[2]
    rules = {
        line.strip()
        for line in (repository / ".dockerignore").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "merak-skills/skills-codex/",
        "merak-skills/skills-codex-claude-review/",
        "merak-skills/skills-codex-gemini-review/",
    } <= rules


def test_all_venue_assets_resolve_from_native_paper_write_templates() -> None:
    roots = PaperDraftingService._template_roots()

    assert len(roots) == 1
    assert roots[0].as_posix().endswith("merak-skills/paper-write/templates")
    assert "skills-codex" not in roots[0].as_posix()
    for bundle in VENUE_TEMPLATE_BUNDLES.values():
        for filename in bundle["assets"]:
            asset = roots[0] / filename
            assert asset.is_file(), filename
            assert asset.stat().st_size > 0, filename


def test_runtime_novelty_and_experiment_policies_match_current_contracts() -> None:
    repository = Path(__file__).resolve().parents[2]
    registry = SkillRegistry()
    assert registry.scan_directory(repository / "merak-skills") > 0
    novelty = registry.get_skill("domain-novelty-check")
    experiment = registry.get_skill("domain-experiment-plan")
    assert novelty is not None and novelty.artifact_contracts == {
        "ideas/SELECTED_IDEA.json": 2,
    }
    assert experiment is not None and experiment.artifact_contracts == {
        "experiments/METHOD_CONTRACT.json": 2,
        "experiments/RUN_SPEC.json": 1,
        "experiments/IMPLEMENTATION_BLUEPRINT.json": 1,
    }
    novelty_text = Path(novelty.file_path).read_text(encoding="utf-8")
    experiment_text = Path(experiment.file_path).read_text(encoding="utf-8")
    assert "Write JSON with `schema: 1`" not in novelty_text
    assert "`METHOD_CONTRACT.json` must use schema 2" in experiment_text


def test_model_svg_skill_owns_complete_svg_without_hybrid_canvas_tools() -> None:
    repository = Path(__file__).resolve().parents[2]
    registry = SkillRegistry()
    registry.scan_directory(repository / "merak-skills")

    skill = registry.get_skill("model-svg-figure")

    assert skill is not None
    assert {
        "prepare_model_svg_draft",
        "submit_model_svg_draft",
        "draft_print_diagnostics",
        "review_figure_svg_composition",
        "generate_figure",
    } <= set(skill.allowed_tools)
    assert {
        "prepare_figure_svg_canvas",
        "append_figure_canvas_primitive",
        "refresh_figure_canvas_runtime",
    }.isdisjoint(skill.allowed_tools)
    content = Path(skill.file_path).read_text(encoding="utf-8")
    assert "The model owns the entire visible composition" in content
    assert "One figure answers one scientific question" in content


def test_active_skill_contracts_have_no_local_agent_cli_directives() -> None:
    repository = Path(__file__).resolve().parents[2]
    skills_root = repository / "merak-skills"
    forbidden = re.compile(
        r"/codex:rescue|\bcodex\s+exec\b|"
        r"\b(?:codex|claude)\s+cli\b|\bclaude\s+code\b|"
        r"CLAUDE_SKILL_DIR|mcp__codex__|\bCodex\s+MCP\b",
        re.IGNORECASE,
    )
    findings: list[str] = []

    for skill_file in sorted(skills_root.glob("*/SKILL.md")):
        if skill_file.parent.name in {
            "skills-codex",
            "skills-codex-claude-review",
            "skills-codex-gemini-review",
        }:
            continue
        for line_number, line in enumerate(
            skill_file.read_text(encoding="utf-8-sig").splitlines(),
            start=1,
        ):
            if forbidden.search(line):
                findings.append(
                    f"{skill_file.relative_to(repository).as_posix()}:"
                    f"{line_number}: {line.strip()}"
                )

    assert findings == []
